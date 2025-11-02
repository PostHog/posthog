import os
import json
import time
import asyncio
from datetime import datetime

import tiktoken
import structlog
from google.genai import Client
from google.genai.types import Content, File, FileData, GenerateContentConfig, MediaResolution, Part, VideoMetadata

logger = structlog.get_logger(__name__)

# Recording (35 minutes): https://us.posthog.com/project/2/replay/0199e6a9-2a17-7209-bcb8-ad1001225d04
# Test moment: 1182s - 1197s

# Recording (2 hours 37 minutes): https://us.posthog.com/project/2/replay/0199e6a1-a8ce-7466-9243-3aaf52af0d9a

VIDEO_TRANSCRIPTION_MODEL_ID = "gemini-2.5-flash-preview-09-2025"
VIDEO_TRANSCRIPTION_MEDIA_RESOLUTION = MediaResolution.MEDIA_RESOLUTION_MEDIUM
VIDEO_TRANSCRIPTION_FRAMES_PER_SECOND = 1
VIDEO_TRANSCRIPTION_MEDIA_RESOLUTION_TO_FRAME_TOKENS_MAPPING = {
    MediaResolution.MEDIA_RESOLUTION_LOW: 66,
    MediaResolution.MEDIA_RESOLUTION_MEDIUM: 258,
    MediaResolution.MEDIA_RESOLUTION_HIGH: 258,
}
VIDEO_TRANSCRIPTION_MODEL_TO_1KK_PRICE_MAPPING = {
    "gemini-2.5-flash-preview-09-2025": {"input": 0.3, "output": 2.5},
}

BASE_PROMPT = """
- Describe what's happening in the video as a a list of salient moments.
- It's a part of the recording of a web analytics session of a user.
- The description will be later combined with other parts to create full transcript of the recording.
- Red lines indicate mouse movements, and should be ignored.
- If nothing is happening - return "Static".
- Output in the `*   **MM:SS - MM:SS:** <description>` format.
"""


class VideoTranscriptioner:
    def __init__(
        self,
        media_duration_s: int,
        media_part_duration_s: int,
        model_id: str = VIDEO_TRANSCRIPTION_MODEL_ID,
        media_resolution: MediaResolution = VIDEO_TRANSCRIPTION_MEDIA_RESOLUTION,
        media_file_name: str | None = None,
        media_file_path: str | None = None,
    ):
        # LLM
        self._encoder = tiktoken.encoding_for_model("o3")
        # Media
        self._media_duration_s = media_duration_s
        self._media_part_duration_s = media_part_duration_s
        self._model_id = model_id
        self._media_resolution = media_resolution
        self._media_file = self._init_media_file(media_file_name, media_file_path)
        # Stats
        self._input_output_tokens_per_part: list[
            tuple[int, int]
        ] = []  # Static parts (nothing happened) should not have tokens counted
        self._prompt_tokens = self._calculate_tokens_from_text(
            BASE_PROMPT
        )  # Defining once, no need to recalculate, as it's static

    def _get_client(self) -> Client:
        # Initializing client on every call to avoid aiohttp "Uncloseed client session" errors for async call
        # Could be fixed in later Gemini library versions
        return Client(api_key=os.getenv("GEMINI_API_KEY"))

    def _init_media_file(self, media_file_name: str | None, media_file_path: str | None) -> File:
        if not media_file_name and not media_file_path:
            raise ValueError("Either media_file_name or media_file_path must be provided")
        if media_file_name and media_file_path:
            raise ValueError("Only one of media_file_name or media_file_path must be provided")
        if media_file_name:
            media_file = self._get_file_from_gemini_files(file_name=media_file_name)
            if not media_file:
                raise ValueError(f"File {media_file_name} not found when transcribing video")
            return media_file
        if media_file_path:
            return self.upload_media_to_gemini(media_file_path=media_file_path)

    def _upload_media_to_gemini_files(self, media_file_path: str) -> File:
        client = self._get_client()
        uploaded_file = client.files.upload(file=media_file_path)
        if not uploaded_file:
            raise ValueError("Failed to upload video to Gemini when transcribing video")
        if not uploaded_file.name:
            raise ValueError("Failed to get name of uploaded video when transcribing video")
        return uploaded_file

    def _get_file_from_gemini_files(self, file_name: str) -> File | None:
        client = self._get_client()
        file = client.files.get(name=file_name)
        if not file:
            raise ValueError(f"File {file_name} not found when transcribing video")
        return file

    def _calculate_tokens_from_text(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encoder.encode(text))

    def _split_duration_into_parts(self) -> list[tuple[int, int]]:
        parts = []
        for i in range(0, self._media_duration_s, self._media_part_duration_s):
            start_offset = i
            end_offset = i + self._media_part_duration_s
            if end_offset > self._media_duration_s:
                end_offset = self._media_duration_s
            parts.append((start_offset, end_offset))
        logger.info(f"Splitting video into {len(parts)} parts")
        return parts

    async def analyze_part(
        self,
        start_offset: str,
        end_offset: str,
    ) -> str | None:
        # Analyze the part
        client = self._get_client()
        logger.info(
            f"Analyzing part with model: {self._model_id}, start_offset: {start_offset}s, end_offset: {end_offset}s"
        )
        response = await client.aio.models.generate_content(
            model=self._model_id,
            contents=Content(
                parts=[
                    Part(
                        file_data=FileData(file_uri=self._media_file.uri, mime_type=self._media_file.mime_type),
                        video_metadata=VideoMetadata(start_offset=f"{start_offset}s", end_offset=f"{end_offset}s"),
                    ),
                    Part(text=BASE_PROMPT),
                ]
            ),
            config=GenerateContentConfig(media_resolution=self._media_resolution),
        )
        # Check if the response is static
        if "Static" in response.text:
            # TODO: Replace with programmatic filter, instead of generating empty summaries (if no events happened during the part)
            return None
        # Calculate stats
        tokens_per_frame = VIDEO_TRANSCRIPTION_MEDIA_RESOLUTION_TO_FRAME_TOKENS_MAPPING[self._media_resolution]
        video_input_tokens = tokens_per_frame * (end_offset - start_offset) * VIDEO_TRANSCRIPTION_FRAMES_PER_SECOND
        input_tokens = video_input_tokens + self._prompt_tokens
        output_tokens = self._calculate_tokens_from_text(response.text)
        self._input_output_tokens_per_part.append((input_tokens, output_tokens))
        # Store the result
        timestamp = datetime.now().isoformat()
        with open(
            f"/Users/woutut/Documents/Code/posthog/playground/video_transcription/"
            f"transcript_{self._model_id}_{self._media_resolution.name}_{start_offset}s-{end_offset}s_{timestamp}.txt",
            "w",
        ) as f:
            f.write(response.text)
        return response.text

    async def analyze_video_in_parts(self) -> dict[str, str]:
        parts = self._split_duration_into_parts()
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for _, (start_offset, end_offset) in enumerate(parts):
                part_key = f"{start_offset}s-{end_offset}s"
                tasks[part_key] = tg.create_task(
                    self.analyze_part(
                        start_offset=start_offset,
                        end_offset=end_offset,
                    )
                )
        transcription = {part_key: task.result() for part_key, task in tasks.items()}
        # Calculate stats
        # Static
        static_parts = len(transcription.keys()) - len(
            self._input_output_tokens_per_part
        )  # Only non-static parts have tokens counted
        logger.info(f"Static parts: {static_parts}")
        logger.info(f"Non-static parts: {len(self._input_output_tokens_per_part)}")
        # Total tokens
        total_input_tokens = sum(tokens[0] for tokens in self._input_output_tokens_per_part)
        total_output_tokens = sum(tokens[1] for tokens in self._input_output_tokens_per_part)
        logger.info(f"Total input tokens: {total_input_tokens}")
        logger.info(f"Total output tokens: {total_output_tokens}")
        # Tokens per part
        input_tokens_per_part = total_input_tokens / len(self._input_output_tokens_per_part)
        output_tokens_per_part = total_output_tokens / len(self._input_output_tokens_per_part)
        logger.info(f"Input tokens per part: {input_tokens_per_part}")
        logger.info(f"Output tokens per part: {output_tokens_per_part}")
        # Tokens price
        input_tokens_price = round(
            total_input_tokens * VIDEO_TRANSCRIPTION_MODEL_TO_1KK_PRICE_MAPPING[self._model_id]["input"] / 1000000, 4
        )
        output_tokens_price = round(
            total_output_tokens * VIDEO_TRANSCRIPTION_MODEL_TO_1KK_PRICE_MAPPING[self._model_id]["output"] / 1000000, 4
        )
        logger.info(f"Input tokens price: {input_tokens_price}")
        logger.info(f"Output tokens price: {output_tokens_price}")
        logger.info(f"Total price: {input_tokens_price + output_tokens_price}")
        # Tokens price per part
        input_tokens_price_per_part = round(input_tokens_price / len(self._input_output_tokens_per_part), 4)
        output_tokens_price_per_part = round(output_tokens_price / len(self._input_output_tokens_per_part), 4)
        logger.info(f"Input tokens price per part: {input_tokens_price_per_part}")
        logger.info(f"Output tokens price per part: {output_tokens_price_per_part}")
        logger.info(f"Total price per part: {input_tokens_price_per_part + output_tokens_price_per_part}")
        return transcription


if __name__ == "__main__":
    # Testing on the video of the chart reload
    # flash lite shows +- the same results at low and at medium
    # flash at low shows also the same results, but flash at medium actually understands what happening (chart recalculation)
    # sticking to flash at medium for the MVP

    input_media_duration_s = 2137
    input_media_part_duration_s = 15
    # input_video_path = (
    #     "/Users/woutut/Desktop/test_videos/replay-0199e6a9-2a17-7209-bcb8-ad1001225d04-2025-11-01-16-50.mp4"
    # )
    input_file_name = "files/1cygz2sk56fn"
    # Define transcriptioner
    transcriptioner = VideoTranscriptioner(
        media_duration_s=input_media_duration_s,
        media_part_duration_s=input_media_part_duration_s,
        media_file_name=input_file_name,
    )
    # Analyze the video
    time_now = time.time()
    transcription = asyncio.run(transcriptioner.analyze_video_in_parts())
    time_after = time.time()
    logger.info(f"Time taken: {time_after - time_now} seconds")
    with open(
        f"/Users/woutut/Documents/Code/posthog/playground/video_transcription/"
        f"full-transcription_{transcriptioner._model_id}_{transcriptioner._media_resolution.name}_"
        f"{transcriptioner._media_duration_s}s_{transcriptioner._media_part_duration_s}s_{datetime.now().isoformat()}.json",
        "w",
    ) as f:
        json.dump(transcription, f, indent=4)
