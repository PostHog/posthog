import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.session_summary.activities.video_based.a4_analyze_video_segment import (
    analyze_video_segment_activity,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    SegmentEventEntry,
    SegmentLlmContext,
    UploadedVideo,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
)

ACTIVITY_MODULE = "posthog.temporal.session_replay.session_summary.activities.video_based.a4_analyze_video_segment"


def _inputs(redis_key_base: str = "test-base") -> VideoSummarySingleSessionInputs:
    return VideoSummarySingleSessionInputs(
        session_id="sess-1",
        user_id=1,
        team_id=1,
        redis_key_base=redis_key_base,
        model_to_use="gemini-test",
    )


def _uploaded() -> UploadedVideo:
    return UploadedVideo(
        file_uri="gs://x/y",
        gemini_file_name="files/abc",
        mime_type="video/mp4",
        duration=120,
    )


def _segment() -> VideoSegmentSpec:
    return VideoSegmentSpec(
        segment_index=0,
        start_time=0,
        end_time=60,
        recording_start_time=0,
        recording_end_time=60,
    )


def _patch_redis_no_events():
    return patch(
        f"{ACTIVITY_MODULE}.get_data_class_from_redis",
        new=AsyncMock(return_value=None),
    )


def _gemini_responder(text: str) -> AsyncMock:
    response = MagicMock()
    response.text = text
    client = MagicMock()
    client.models.generate_content = AsyncMock(return_value=response)
    factory = MagicMock(return_value=client)
    return factory


@pytest.mark.asyncio
async def test_raises_when_redis_key_base_missing():
    inputs = _inputs(redis_key_base="")
    with pytest.raises(ApplicationError, match="No Redis key base"):
        await ActivityEnvironment().run(
            analyze_video_segment_activity, inputs, _uploaded(), _segment(), "trace", "team"
        )


@pytest.mark.asyncio
async def test_parses_bullet_segments_from_llm_response():
    bullets = "* 00:05 - 00:15: User opens login page\n* 00:20 - 00:40: User enters credentials"
    factory = _gemini_responder(bullets)

    with (
        _patch_redis_no_events(),
        patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory),
    ):
        result = await ActivityEnvironment().run(
            analyze_video_segment_activity, _inputs(), _uploaded(), _segment(), "trace", "team"
        )

    assert len(result) == 2
    assert result[0].description == "User opens login page"
    assert result[1].description == "User enters credentials"


@pytest.mark.asyncio
async def test_skips_bullets_with_inverted_timestamps():
    bullets = "* 00:30 - 00:10: Bad range gets dropped\n* 00:05 - 00:15: Good range kept"
    factory = _gemini_responder(bullets)

    with (
        _patch_redis_no_events(),
        patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory),
    ):
        result = await ActivityEnvironment().run(
            analyze_video_segment_activity, _inputs(), _uploaded(), _segment(), "trace", "team"
        )

    assert len(result) == 1
    assert result[0].description == "Good range kept"


@pytest.mark.asyncio
async def test_returns_empty_when_response_has_no_bullets():
    factory = _gemini_responder("Some plain text without bullet structure")

    with (
        _patch_redis_no_events(),
        patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory),
    ):
        result = await ActivityEnvironment().run(
            analyze_video_segment_activity, _inputs(), _uploaded(), _segment(), "trace", "team"
        )

    assert result == []


@pytest.mark.asyncio
async def test_passes_cached_events_into_prompt_when_redis_hit():
    cached_context = SegmentLlmContext(
        events=[
            SegmentEventEntry(event_id="evt-1", data=["evt-1", "click", "/login"]),
            SegmentEventEntry(event_id="evt-2", data=["evt-2", "submit", "/login"]),
        ],
        simplified_events_columns=["event_id", "$event_type", "$current_url"],
        url_mapping_reversed={"/login": "https://app.example.com/login"},
        window_mapping_reversed={},
        session_start_time_str="2024-01-01T00:00:00Z",
    )
    factory = _gemini_responder("* 00:00 - 00:30: User logged in")
    captured_prompt: list[str] = []

    async def _capture_generate(**kwargs):
        for item in kwargs.get("contents", []):
            if isinstance(item, str):
                captured_prompt.append(item)
        response = MagicMock()
        response.text = "* 00:00 - 00:30: User logged in"
        return response

    factory.return_value.models.generate_content = AsyncMock(side_effect=_capture_generate)

    with (
        patch(f"{ACTIVITY_MODULE}.get_data_class_from_redis", new=AsyncMock(return_value=cached_context)),
        patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory),
    ):
        result = await ActivityEnvironment().run(
            analyze_video_segment_activity, _inputs(), _uploaded(), _segment(), "trace", "team"
        )

    assert len(result) == 1
    assert captured_prompt, "Prompt should have been captured"
    prompt_text = captured_prompt[0]
    assert "<tracked_events>" in prompt_text
    assert "evt-1" in prompt_text
    assert "evt-2" in prompt_text


@pytest.mark.asyncio
async def test_omits_events_section_when_redis_returns_empty_events():
    cached_context = SegmentLlmContext(
        events=[],
        simplified_events_columns=["event_id"],
        url_mapping_reversed={},
        window_mapping_reversed={},
        session_start_time_str="2024-01-01T00:00:00Z",
    )
    factory = _gemini_responder("* 00:00 - 00:30: Static")
    captured_prompt: list[str] = []

    async def _capture_generate(**kwargs):
        for item in kwargs.get("contents", []):
            if isinstance(item, str):
                captured_prompt.append(item)
        response = MagicMock()
        response.text = "* 00:00 - 00:30: Static"
        return response

    factory.return_value.models.generate_content = AsyncMock(side_effect=_capture_generate)

    with (
        patch(f"{ACTIVITY_MODULE}.get_data_class_from_redis", new=AsyncMock(return_value=cached_context)),
        patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory),
    ):
        await ActivityEnvironment().run(
            analyze_video_segment_activity, _inputs(), _uploaded(), _segment(), "trace", "team"
        )

    assert "<tracked_events>" not in captured_prompt[0]
