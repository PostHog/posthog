import asyncio
import json
import os
from pathlib import Path
from google.genai.types import GenerateContentConfig, ThinkingConfig
import markdown_to_json
from google.genai import Client
import structlog
from tqdm.asyncio import tqdm

logger = structlog.get_logger(__name__)

FEATURE_DETECTION_MODEL_ID = "gemini-2.5-flash-preview-09-2025"

BASE_FEATURE_DECTION_PROMPT = """
- Check the transcription of the web analytics session
- Detect what products the user used (without timestamps) within the session
- Detect what features the user used within the product
- Describe briefly (in 3-4 words) how the user used the feature
- Pick up to 10 mostly important actions per feature
- Don't include non-feature-specific actions, like clicks or scrolls
- All the products/features are part of the PostHog platform, so don't mention `PostHog` in the names of the products/features
- Avoid including user-generated data (like emails, names of the specific reports, etc.)

- Return in the format, using the example.

The example:

```
- Google Mail
  - Emails
    * checked unreads
    * sent an email
- Google Calendar
  - TODO
    * added a reminder
  - Calendar
    * re-scheduled a meeting
    * changed the timezone
- Google Maps
  - Map
    * searched for a restaurant
  ...
...
```

The transcription:
{transcription}
"""


def _get_client() -> Client:
    # Initializing client on every call to avoid aiohttp "Uncloseed client session" errors for async call
    # Could be fixed in later Gemini library versions
    return Client(api_key=os.getenv("GEMINI_API_KEY"))


async def detect_features_task(session_id: str, transcription: str, output_path: Path) -> None:
    try:
        transcription_output_path_raw = (
            output_path / session_id / f"feature-detection_{FEATURE_DETECTION_MODEL_ID}_raw.txt"
        )
        transcription_output_path_json = (
            output_path / session_id / f"feature-detection_{FEATURE_DETECTION_MODEL_ID}_json.json"
        )
        # Check if the transcription already exists
        # if transcription_output_path_raw.exists() and transcription_output_path_json.exists():
        #     logger.info(f"Transcription for session {session_id} already exists, skipping")
        #     return None
        # Generate the transcription
        prompt = BASE_FEATURE_DECTION_PROMPT.format(transcription=transcription)
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=FEATURE_DETECTION_MODEL_ID,
            contents=[prompt],
            config=GenerateContentConfig(
                thinking_config=ThinkingConfig(thinking_budget=1024)
            ),
        )
        with open(transcription_output_path_raw, "w") as f:
            f.write(response.text)
        with open(transcription_output_path_json, "w") as f:
            json_data = markdown_to_json.dictify(response.text)
            json.dump(json_data, f)
        return None
    except Exception as e:
        logger.error(f"Error detecting features for session {session_id}: {e}")
        # Let handler catch the exception
        return e


async def detect_features(session_id_to_transcription: dict[str, str], output_path: Path) -> None:
    # Split into chunks of 10 to process lots, but not oveload the API
    chunk_size = 10
    chunks = [
        list(session_id_to_transcription.items())[i : i + chunk_size]
        for i in range(0, len(session_id_to_transcription), chunk_size)
    ]
    for chunk in tqdm(chunks, desc="Detecting features in chunks"):
        chunk_tasks = []
        async with asyncio.TaskGroup() as tg:
            for session_id, transcription in chunk:
                chunk_tasks.append(
                    tg.create_task(
                        detect_features_task(
                            session_id=session_id, transcription=transcription, output_path=output_path
                        )
                    )
                )
        for result in chunk_tasks:
            if isinstance(result, Exception):
                continue
            logger.info(f"Successfully detected features for session {session_id}")
    return None


if __name__ == "__main__":
    # /Users/woutut/Documents/Code/posthog/playground/feature_detection/transcription/0199eb90-aa8d-7ae9-8186-21dc43c9acef/str-transcription_gemini-2.5-flash-preview-09-2025_MEDIA_RESOLUTION_MEDIUM_305s_15s_2025-11-07T14:11:49.228801.txt
    base_transcriptions_path = Path("/Users/woutut/Documents/Code/posthog/playground/feature_detection/transcription/")
    # Iterate over session folders and pick transcription files (starts with `str-`)
    input_session_id_to_transcription = {}
    for session_folder in base_transcriptions_path.iterdir():
        if not session_folder.is_dir():
            continue
        # Iterate over transcription files in the session folder
        for transcription_file in session_folder.iterdir():
            if not transcription_file.is_file():
                continue
            if not transcription_file.name.startswith("str-"):
                continue
            with open(transcription_file, "r") as f:
                transcription = f.read()
            session_id = session_folder.name
            input_session_id_to_transcription[session_id] = transcription
    asyncio.run(
        detect_features(
            session_id_to_transcription=input_session_id_to_transcription,
            output_path=base_transcriptions_path,
        )
    )
