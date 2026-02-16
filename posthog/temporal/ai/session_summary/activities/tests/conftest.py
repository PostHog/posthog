"""
Fixtures for video-based session summary activity tests.

This module provides fixtures that build on the existing test infrastructure from posthog/temporal/tests/ai/conftest.py
and ee/hogai/session_summaries/tests/conftest.py.
"""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.models.exported_asset import ExportedAsset
from posthog.models.user import User
from posthog.temporal.ai.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    UploadedVideo,
    VideoSegmentOutcome,
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSessionOutcome,
    VideoSummarySingleSessionInputs,
)

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL, FULL_VIDEO_EXPORT_FORMAT

# Re-use the fixtures of session summaries tests for convenience
from ee.hogai.session_summaries.tests.conftest import *  # noqa: F401, F403


@pytest.fixture
def organization():
    """A test organization."""
    name = f"VideoTestOrg-{random.randint(1, 99999)}"
    org = Organization.objects.create(name=name, is_ai_data_processing_approved=True)
    org.save()

    yield org

    org.delete()


@pytest.fixture
def team(organization):
    """A test team."""
    name = f"VideoTestTeam-{random.randint(1, 99999)}"
    team = Team.objects.create(organization=organization, name=name)
    team.save()

    yield team

    team.delete()


@pytest_asyncio.fixture
async def aorganization():
    name = f"VideoTestOrg-{random.randint(1, 99999)}"
    org = await sync_to_async(Organization.objects.create)(name=name, is_ai_data_processing_approved=True)

    yield org

    await sync_to_async(org.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    name = f"VideoTestTeam-{random.randint(1, 99999)}"
    team = await sync_to_async(Team.objects.create)(organization=aorganization, name=name)

    yield team

    await sync_to_async(team.delete)()


@pytest_asyncio.fixture
async def auser(aorganization):
    user = await sync_to_async(User.objects.create_and_join)(
        aorganization, f"video-test-{random.randint(1, 99999)}@posthog.com", "testpassword123", "Test"
    )
    yield user
    await sync_to_async(user.delete)()


@pytest.fixture
def mock_video_session_id() -> str:
    """A test session ID for video tests."""
    return "00000000-0000-0000-0002-000000000000"


def create_video_summary_inputs(
    session_id: str,
    team_id: int,
    user_id: int,
    redis_key_base: str = "test_video_key_base",
    model_to_use: str = DEFAULT_VIDEO_UNDERSTANDING_MODEL,
    user_distinct_id_to_log: str | None = None,
) -> VideoSummarySingleSessionInputs:
    """Create VideoSummarySingleSessionInputs for testing."""
    return VideoSummarySingleSessionInputs(
        session_id=session_id,
        user_id=user_id,
        team_id=team_id,
        redis_key_base=redis_key_base,
        model_to_use=model_to_use,
        user_distinct_id_to_log=user_distinct_id_to_log,
    )


@pytest.fixture
def mock_uploaded_video() -> UploadedVideo:
    """Mock Gemini uploaded video reference."""
    return UploadedVideo(
        file_uri="https://generativelanguage.googleapis.com/v1beta/files/abc123",
        mime_type=FULL_VIDEO_EXPORT_FORMAT,
        duration=120,  # 2 minutes
    )


@pytest.fixture
def mock_video_segment_specs() -> list[VideoSegmentSpec]:
    """Mock video segment specifications for a 2-minute video with 15s chunks."""
    return [
        VideoSegmentSpec(segment_index=0, start_time=0.0, end_time=15.0),
        VideoSegmentSpec(segment_index=1, start_time=15.0, end_time=30.0),
        VideoSegmentSpec(segment_index=2, start_time=30.0, end_time=45.0),
        VideoSegmentSpec(segment_index=3, start_time=45.0, end_time=60.0),
        VideoSegmentSpec(segment_index=4, start_time=60.0, end_time=75.0),
        VideoSegmentSpec(segment_index=5, start_time=75.0, end_time=90.0),
        VideoSegmentSpec(segment_index=6, start_time=90.0, end_time=105.0),
        VideoSegmentSpec(segment_index=7, start_time=105.0, end_time=120.0),
    ]


@pytest.fixture
def mock_video_segment_outputs() -> list[VideoSegmentOutput]:
    """Mock raw video segment analysis outputs."""
    return [
        VideoSegmentOutput(
            start_time="00:00",
            end_time="00:05",
            description="User opened the dashboard and clicked on the navigation menu",
        ),
        VideoSegmentOutput(
            start_time="00:05",
            end_time="00:12",
            description="User scrolled through the list of projects",
        ),
        VideoSegmentOutput(
            start_time="00:12",
            end_time="00:18",
            description="User clicked 'Create new project' button",
        ),
        VideoSegmentOutput(
            start_time="00:18",
            end_time="00:30",
            description="User filled out the project creation form with name 'My Test Project'",
        ),
        VideoSegmentOutput(
            start_time="00:30",
            end_time="00:35",
            description="User clicked submit button but received validation error 'Name already exists'",
        ),
        VideoSegmentOutput(
            start_time="00:35",
            end_time="00:45",
            description="User changed project name to 'My Test Project 2' and submitted successfully",
        ),
    ]


@pytest.fixture
def mock_consolidated_video_analysis() -> ConsolidatedVideoAnalysis:
    """Mock consolidated video analysis."""
    return ConsolidatedVideoAnalysis(
        segments=[
            ConsolidatedVideoSegment(
                title="Dashboard navigation",
                start_time="00:00",
                end_time="00:12",
                description="User navigated through the dashboard and viewed project list",
                success=True,
                exception=None,
                confusion_detected=False,
                abandonment_detected=False,
            ),
            ConsolidatedVideoSegment(
                title="Project creation attempt",
                start_time="00:12",
                end_time="00:45",
                description="User attempted to create a new project, encountered validation error, then successfully created project with modified name",
                success=True,
                exception="non-blocking",
                confusion_detected=False,
                abandonment_detected=False,
            ),
        ],
        session_outcome=VideoSessionOutcome(
            success=True,
            description="User successfully created a new project after resolving a naming conflict",
        ),
        segment_outcomes=[
            VideoSegmentOutcome(
                segment_index=0,
                success=True,
                summary="Successfully navigated dashboard",
            ),
            VideoSegmentOutcome(
                segment_index=1,
                success=True,
                summary="Successfully created project after retry",
            ),
        ],
    )


@pytest.fixture
def mock_gemini_file_response() -> MagicMock:
    """Mock Gemini Files API response."""
    mock_file = MagicMock()
    mock_file.name = "files/abc123"
    mock_file.uri = "https://generativelanguage.googleapis.com/v1beta/files/abc123"
    mock_file.mime_type = FULL_VIDEO_EXPORT_FORMAT
    mock_file.state = MagicMock()
    mock_file.state.name = "ACTIVE"
    return mock_file


@pytest.fixture
def mock_gemini_processing_file_response() -> MagicMock:
    """Mock Gemini Files API response while processing."""
    mock_file = MagicMock()
    mock_file.name = "files/abc123"
    mock_file.uri = None
    mock_file.mime_type = FULL_VIDEO_EXPORT_FORMAT
    mock_file.state = MagicMock()
    mock_file.state.name = "PROCESSING"
    return mock_file


@pytest.fixture
def mock_gemini_generate_response() -> MagicMock:
    """Mock Gemini LLM generation response."""
    mock_response = MagicMock()
    mock_response.text = """* 00:00 - 00:05: User opened the dashboard and clicked on the navigation menu
* 00:05 - 00:12: User scrolled through the list of projects
* 00:12 - 00:18: User clicked 'Create new project' button"""
    return mock_response


@pytest.fixture
def mock_gemini_consolidation_response(mock_consolidated_video_analysis: ConsolidatedVideoAnalysis) -> MagicMock:
    """Mock Gemini LLM consolidation response with JSON."""
    import json

    mock_response = MagicMock()
    mock_response.text = f"```json\n{json.dumps(mock_consolidated_video_analysis.model_dump())}\n```"
    return mock_response


@pytest_asyncio.fixture
async def mock_exported_asset(ateam, auser, mock_video_session_id: str):
    """Create test ExportedAsset with video content."""
    asset = await ExportedAsset.objects.acreate(
        team_id=ateam.id,
        export_format=FULL_VIDEO_EXPORT_FORMAT,
        export_context={
            "session_recording_id": mock_video_session_id,
            "timestamp": 0,
            "filename": f"test-video-{mock_video_session_id}",
            "duration": 120,
            "playback_speed": 2,
            "mode": "video",
        },
        created_by_id=auser.id,
        created_at=datetime.now(UTC),
        expires_after=datetime.now(UTC) + timedelta(days=7),
        content=b"\x00\x00\x00\x1c\x66\x74\x79\x70\x69\x73\x6f\x6d\x00\x00\x02\x00",  # Minimal video content
    )
    yield asset
    await asset.adelete()


@pytest.fixture
def mock_video_session_metadata() -> dict[str, Any]:
    """Mock session replay metadata from ClickHouse."""
    return {
        "session_id": "00000000-0000-0000-0002-000000000000",
        "distinct_id": "test_distinct_id",
        "duration": 120,  # seconds
        "start_time": datetime(2025, 3, 31, 18, 40, 32, 302000, tzinfo=UTC),
        "end_time": datetime(2025, 3, 31, 18, 42, 32, 302000, tzinfo=UTC),
        "click_count": 25,
        "keypress_count": 50,
        "mouse_activity_count": 200,
        "console_log_count": 3,
        "console_warn_count": 1,
        "console_error_count": 0,
        "start_url": "https://app.posthog.com/dashboard",
        "storage": "object_storage",
    }


@pytest.fixture
def mock_short_session_metadata() -> dict[str, Any]:
    """Mock metadata for a short session that should be skipped."""
    return {
        "session_id": "00000000-0000-0000-0002-000000000001",
        "distinct_id": "test_distinct_id",
        "duration": 2,  # Too short (less than MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S)
        "start_time": datetime(2025, 3, 31, 18, 40, 32, 302000, tzinfo=UTC),
        "end_time": datetime(2025, 3, 31, 18, 40, 34, 302000, tzinfo=UTC),
    }


@pytest.fixture
def mock_gemini_client() -> MagicMock:
    """Mock Google GenAI client."""
    mock_client = MagicMock()
    mock_client.files = MagicMock()
    mock_client.files.upload = MagicMock()
    mock_client.files.get = MagicMock()
    return mock_client


@pytest.fixture
def mock_async_gemini_client() -> MagicMock:
    """Mock async Google GenAI client for LLM calls."""
    mock_client = MagicMock()
    mock_client.models = MagicMock()
    mock_client.models.generate_content = AsyncMock()
    return mock_client
