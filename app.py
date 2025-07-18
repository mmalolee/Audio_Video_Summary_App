import streamlit as st
from pydub import AudioSegment
from io import BytesIO
from dotenv import dotenv_values
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from hashlib import md5


###########
# SECRETS #
###########

env = dotenv_values('.env')

if 'QDRANT_URL' in st.secrets:
    env['QDRANT_URL'] = st.secrets['QDRANT_URL']
if 'QDRANT_API' in st.secrets:
    env['QDRANT_API'] = st.secrets['QDRANT_API']


#############
# CONSTANTS #
#############

TRANSCRIPTION_MODEL = 'whisper-1'
SUMMARY_MODEL = 'gpt-4o'
EMBEDDING_MODEL = 'text-embedding-3-large'
EMBEDDING_DIM = 3072
COLLECTION_NAME = 'SUMMARIES'


##############
# FILE BYTES #
##############

def convert_user_file(uploaded_user_file):
    audio_segment = AudioSegment.from_file(uploaded_user_file)
    audio_box_mp3 = audio_segment.export(BytesIO(), format='mp3')
    audio_bytes = audio_box_mp3.getvalue()
    return audio_bytes


##########
# OPENAI #
##########

@st.cache_resource
def get_openai_client():
    return OpenAI(api_key=st.session_state['api_key'])


def transcribe_audio(bytes):
    openai_client = get_openai_client()
    bytes_file = BytesIO(bytes)
    bytes_file.name = 'audio.mp3'
    response = openai_client.audio.transcriptions.create(
        model=TRANSCRIPTION_MODEL,
        file=bytes_file,
        response_format='verbose_json'
    )
    return response.text


def summary(audio_transcription):
    openai_client = get_openai_client()
    prompt = '''Streść następujący tekst w sposób zwięzły, 
    zachowując wszystkie kluczowe informacje, fakty, sens oryginału i poprawność językową. 
    Wypowiadaj się w trzeciej osobie. Przetłumacz na język angielski.
    Unikaj ogólników, skup się na konkretach i głównych punktach przekazu: '''
    response = openai_client.chat.completions.create(
        model=SUMMARY_MODEL,
        temperature=0,
        messages=[
            {
                'role': 'user',
                'content': f'{prompt}: {audio_transcription}'
            }
        ]
    )
    return response.choices[0].message.content


def get_embedding(audio_summary):
    openai_client = get_openai_client()
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[audio_summary],
        dimensions=EMBEDDING_DIM
    )
    return response.data[0].embedding


##########
# QDRANT #
##########

@st.cache_resource
def get_qdrant_client():
    return QdrantClient(
    url=env['QDRANT_URL'], 
    api_key=env['QDRANT_API'],
)


def check_if_collection_exists():
    qdrant_client = get_qdrant_client()
    if not qdrant_client.collection_exists(collection_name=COLLECTION_NAME):
        print('Creating collection')
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE
            )
        )
    else: 
        print('Collection exists')


def add_note_to_qdrant(audio_text_summary):
    qdrant_client = get_qdrant_client()
    total_number_of_points = qdrant_client.count(
        collection_name=COLLECTION_NAME,
        exact=True).count
    qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=total_number_of_points+1,
                vector=get_embedding(audio_text_summary),
                payload={'summary': audio_text_summary}
            )
        ]
    )


def list_notes_from_qdrant(query=None):
    qdrant_client = get_qdrant_client()
    if not query:
        summaries = qdrant_client.scroll(collection_name=COLLECTION_NAME, limit=10)[0]
        result = []
        for summary in summaries:
            result.append(
                {
                    'text': summary.payload['summary'],
                    'score': None
                }
            )
        return result
    else:
        summaries = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=get_embedding(query),
            limit=10
        )
        result = []
        for summary in summaries:
            result.append(
                {
                    'text': summary.payload['summary'],
                    'score': summary.score
                }
            )
        return result            


##################
# SESSION_STATES #
##################

if 'audio_bytes' not in st.session_state:
    st.session_state['audio_bytes'] = ''

if 'video_bytes' not in st.session_state:
    st.session_state['video_bytes'] = ''

if 'audio_bytes_md5' not in st.session_state:
    st.session_state['audio_bytes_md5'] = ''

if 'video_bytes_md5' not in st.session_state:
    st.session_state['video_bytes_md5'] = ''

if 'audio_summary' not in st.session_state:
    st.session_state['audio_summary'] = ''

if 'video_summary' not in st.session_state:
    st.session_state['video_summary'] = ''


######################
# ASKING FOR API-KEY #
######################

if not st.session_state.get('api_key'):
    st.info('Enter your OpenAI API key')
    st.session_state['api_key'] = st.text_input('OpenAI API Key', type='password')
    if st.session_state['api_key']:
        st.rerun()
    st.stop()


########
# MAIN #
########

st.title(':camera: :speaker: Audio/Video Summary :speaker: :camera:')
st.header('Upload your file and create a summary')

check_if_collection_exists()

audio_tab, video_tab, search_tab = st.tabs(['Audio', 'Video', 'Search Summary'])

with audio_tab:
    uploaded_user_audio_file = st.file_uploader('Upload Audio File', type=['mp3', 'wav'])

    if uploaded_user_audio_file:
        st.session_state['audio_bytes'] = convert_user_file(uploaded_user_audio_file)
        st.audio(st.session_state['audio_bytes'])

        current_md5 = md5(st.session_state['audio_bytes']).hexdigest()

        if current_md5 != st.session_state['audio_bytes_md5']:
                st.session_state['audio_summary'] = ''
                st.session_state['audio_bytes_md5'] = current_md5

        if st.button("Generate Audio Summary", use_container_width=True):
            audio_to_text = transcribe_audio(st.session_state['audio_bytes'])
            st.session_state['audio_summary'] = summary(audio_to_text)

        if st.session_state['audio_summary'] != '':
            with st.expander('Summary', expanded=True):
                st.text_area(
                    label='Audio Summary',
                    value=st.session_state['audio_summary'],
                    disabled=True
                    )
                
                if st.button('Save Audio Summary', use_container_width=True):
                    add_note_to_qdrant(st.session_state['audio_summary'])
                    st.success('Audio Summary Has Been Saved')

                                   
with video_tab:
    uploaded_user_video_file = st.file_uploader('Upload Video File', type='mp4')

    if uploaded_user_video_file:
        st.video(uploaded_user_video_file)
        st.session_state['video_bytes'] = convert_user_file(uploaded_user_video_file)

        current_md5 = md5(st.session_state['video_bytes']).hexdigest()

        if current_md5 != st.session_state['video_bytes_md5']:
            st.session_state['video_bytes_md5'] = current_md5
            st.session_state['video_summary'] = ''

        if st.button('Generate Video Summary', use_container_width=True):
            video_to_text = transcribe_audio(st.session_state['video_bytes'])
            st.session_state['video_summary'] = summary(video_to_text)

        if st.session_state['video_summary'] != '':
            with st.expander('Summary', expanded=True):
                st.text_area(
                    label='Video Summary',
                    value=st.session_state['video_summary'],
                    disabled=True
                    )
                
                if st.button('Save Video Summary', use_container_width=True):
                    add_note_to_qdrant(st.session_state['video_summary'])
                    st.success('Video Summary Has Been Saved')

with search_tab:
    query = st.text_input('Search a Summary')

    if st.button('Search', use_container_width=True):
        for searched in list_notes_from_qdrant(query):
            with st.container(border=True):
                st.write(searched['text'])

                if searched['score']:
                    st.metric(f"Similarity: ", round(searched['score'], 2))
        
        
    