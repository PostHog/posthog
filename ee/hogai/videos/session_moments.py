import uuid
import asyncio
from dataclasses import dataclass
from math import ceil

import structlog
from google import genai
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.constants import VIDEO_EXPORT_TASK_QUEUE
from posthog.models.exported_asset import ExportedAsset
from posthog.models.user import User
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs, VideoExportWorkflow

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SessionMomentInput:
    # ID to identify the moment in mappings (for example, event_uuid)
    moment_id: str
    # Timestamp to start the video from
    timestamp_s: int
    # How long the video should be
    duration_s: int


class SessionMomentsLLMAnalyzer:
    """Generate videos for Replay session events and analyze them with LLM"""

    def __init__(self, session_id: str, team_id: int, user: User, prompt: str, failed_moments_min_ratio: float):
        self.session_id = session_id
        self.team_id = team_id
        self.user = user
        self.prompt = prompt
        # If less than N% of moments were generated, fail the analysis
        # Allow as an input as the expected success ratio could differ from task to tasks
        self._failed_moments_min_ratio = failed_moments_min_ratio

    async def analyze(self, moments: list[SessionMomentInput]) -> dict[str, str]:
        """Analyze the session moments with LLM and return mapping of moment_id to LLM analysis"""
        # Generate videos
        asset_ids = await self._generate_videos_for_moments(moments)
        # Analyze videos with LLM
        results = await self._analyze_moment_videos_with_llm(asset_ids, "Please analyze the session moments.")
        return results

    async def _generate_videos_for_moments(self, moments: list[SessionMomentInput]) -> dict[str, int]:
        """Generate videos for moments and return mapping of moment_id to asset_id"""
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for moment in moments:
                tasks[moment.moment_id] = tg.create_task(self._generate_video_for_single_moment(moment))
        # Collect asset IDs
        moment_to_asset_id = {}
        for moment_id, task in tasks.items():
            res = task.result()
            if isinstance(res, Exception):
                logger.exception(
                    f"Failed to generate video for moment {moment} from session {self.session_id} of team {self.team_id}: {res}"
                )
                # Not failing explicitly to avoid failing all the generations if one fails
                continue
            moment_to_asset_id[moment_id] = await task
        # Check if enough moments were generated
        expected_min_moments = ceil(len(moments) * self._failed_moments_min_ratio)
        if expected_min_moments > len(moment_to_asset_id):
            exception_message = f"Not enough moments were generated for session {self.session_id} of team {self.team_id}: {len(moment_to_asset_id)} out of {len(moments)}, expected at least {expected_min_moments}"
            logger.exception(exception_message)
            raise Exception(exception_message)
        return moment_to_asset_id

    def _generate_moment_video_filename(self, moment_id: str) -> str:
        """Generate a filename for a moment video"""
        return f"session-moment_{self.session_id}_{moment_id}"

    async def _generate_video_for_single_moment(self, moment: SessionMomentInput) -> int | Exception:
        """Generate a video for an event in Replay session and return the asset ID"""
        try:
            moment_filename = self._generate_moment_video_filename(moment.moment_id)
            exported_asset = await ExportedAsset.objects.acreate(
                team_id=self.team_id,
                export_format="video/mp4",
                export_context={
                    "session_recording_id": self.session_id,
                    "timestamp": moment.timestamp_s,
                    "filename": moment_filename,
                    "duration": moment.duration_s,
                    # Keeping default values
                    "mode": "screenshot",
                    "css_selector": ".replayer-wrapper",
                    "width": 1987,
                    "height": 1312,
                },
                created_by=self.user,
            )
            # Generate a video through Temporal workflow
            client = await async_connect()
            await client.execute_workflow(
                VideoExportWorkflow.run,
                VideoExportInputs(exported_asset_id=exported_asset.id),
                id=f"session-moment-video-export_{self.session_id}_{moment.moment_id}_{uuid.uuid4()}",
                task_queue=VIDEO_EXPORT_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
            # Return the asset ID for later retrieval
            return exported_asset.id
        except Exception as err:  # Workflow retries exhausted
            # Let caller handle the error
            return err

    async def _get_video_bytes(self, asset_id: int) -> bytes | None:
        """Retrieve video content as bytes for an ExportedAsset ID"""
        try:
            # Fetch the asset from the database
            asset = await ExportedAsset.objects.aget(id=asset_id)
            # Get content from either database or object storage
            if asset.content:
                # TODO: Decide if the check is needed
                # Content stored directly in database
                return bytes(asset.content)
            elif asset.content_location:
                # Content stored in object storage
                return await database_sync_to_async(object_storage.read_bytes, thread_sensitive=False)(
                    asset.content_location
                )
            else:
                return None
        except ExportedAsset.DoesNotExist:
            return None

    async def _analyze_single_moment_video_with_llm(
        self,
        asset_id: int,
        moment_id: str,
    ) -> str | None | Exception:
        """Analyze a moment video with LLM"""
        try:
            video_bytes = await self._get_video_bytes(asset_id)
            if not video_bytes:
                logger.warning(
                    f"No video bytes found for asset {asset_id} for moment {moment_id} of session {self.session_id} of team {self.team_id}"
                )
                return None
            if len(video_bytes) > 20 * 1024 * 1024:  # 20MB limit
                logger.warning(
                    f"Video bytes for asset {asset_id} for moment {moment_id} of session {self.session_id} of team {self.team_id} are too large"
                )
                return None
            # TODO: Remove after testing, storing for debugging
            with open(f"video_{moment_id}.mp4", "wb") as f:
                f.write(video_bytes)
            # Get response from LLM
            client = genai.Client()
            response = client.models.generate_content(
                model="models/gemini-2.5-flash",
                contents=genai.types.Content(
                    parts=[
                        genai.types.Part(inline_data=genai.types.Blob(data=video_bytes, mime_type="video/mp4")),
                        genai.types.Part(text=self.prompt),
                    ]
                ),
            )
            content = response.text
            if not content:
                logger.warning(
                    f"No LLM content found for moment {moment_id} of session {self.session_id} of team {self.team_id}"
                )
                return None
            return content
        except Exception as err:
            logger.exception(
                f"Failed to analyze moment video {moment_id} of session {self.session_id} of team {self.team_id} with LLM: {err}"
            )
            return err  # Let caller handle the error

    async def _analyze_moment_videos_with_llm(self, asset_ids: dict[str, int]) -> dict[str, str]:
        """Send videos to LLM for validation and get analysis results"""
        tasks = {}
        async with asyncio.TaskGroup() as tg:
            for moment_id, asset_id in asset_ids.items():
                tasks[moment_id] = tg.create_task(self._analyze_single_moment_video_with_llm(asset_id, moment_id))
        results = {}
        for moment_id, task in tasks.items():
            res = task.result()
            if isinstance(res, Exception):
                logger.exception(
                    f"Failed to analyze moment video {moment_id} of session {self.session_id} of team {self.team_id} with LLM: {res}"
                )
                continue
            if not res:
                continue
            results[moment_id] = res
        # No additional check for how many moments were analyzed as they can be limited by video size
        return results