import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from google.genai import errors as genai_errors
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.session_summary.activities.video_based.a6_consolidate_video_segments import (
    _validate_tagging_output,
    consolidate_video_segments_activity,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    SessionTaggingOutput,
    VideoSegmentOutput,
    VideoSummarySingleSessionInputs,
)

ACTIVITY_MODULE = "posthog.temporal.session_replay.session_summary.activities.video_based.a6_consolidate_video_segments"


def _inputs() -> VideoSummarySingleSessionInputs:
    return VideoSummarySingleSessionInputs(
        session_id="sess-1",
        user_id=1,
        team_id=1,
        redis_key_base="test",
        model_to_use="gemini-test",
    )


def _raw_segments() -> list[VideoSegmentOutput]:
    return [
        VideoSegmentOutput(start_time="00:00", end_time="00:30", description="User logs in"),
        VideoSegmentOutput(start_time="00:30", end_time="01:00", description="User browses dashboard"),
    ]


def _consolidated_response() -> dict:
    return {
        "segments": [
            {
                "title": "Login flow",
                "start_time": "00:00",
                "end_time": "00:30",
                "description": "Logged in",
                "success": True,
            },
            {
                "title": "Dashboard exploration",
                "start_time": "00:30",
                "end_time": "01:00",
                "description": "Browsed dashboard",
                "success": True,
            },
        ],
        "session_outcome": {"success": True, "description": "User completed login and explored dashboard"},
        "segment_outcomes": [
            {"segment_index": 0, "success": True, "summary": "OK"},
            {"segment_index": 1, "success": True, "summary": "OK"},
        ],
        "fix_suggestions": [],
    }


def _tagging_response() -> dict:
    return {"tags_fixed": ["onboarding"], "tags_freeform": ["dashboard"], "highlighted": False}


def _mock_genai_with_responses(responses: list[dict]) -> MagicMock:
    response_objs = []
    for r in responses:
        m = MagicMock()
        m.text = json.dumps(r)
        response_objs.append(m)
    client = MagicMock()
    client.models.generate_content = AsyncMock(side_effect=response_objs)
    return MagicMock(return_value=client)


@pytest.mark.asyncio
async def test_raises_non_retryable_when_no_raw_segments():
    with pytest.raises(ApplicationError) as exc_info:
        await ActivityEnvironment().run(consolidate_video_segments_activity, _inputs(), [], "trace")
    assert exc_info.value.non_retryable is True


@pytest.mark.asyncio
async def test_consolidates_raw_segments_into_semantic_segments():
    factory = _mock_genai_with_responses([_consolidated_response(), _tagging_response()])
    with patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory):
        result = await ActivityEnvironment().run(
            consolidate_video_segments_activity, _inputs(), _raw_segments(), "trace"
        )

    assert len(result["consolidated_analysis"].segments) == 2
    assert result["consolidated_analysis"].segments[0].title == "Login flow"
    assert result["consolidated_analysis"].session_outcome.success is True
    assert result["tagging"].tags_fixed == ["onboarding"]


@pytest.mark.asyncio
async def test_retries_when_llm_response_is_invalid_json():
    # First response is invalid JSON, second response is valid — activity should retry
    bad = MagicMock()
    bad.text = "not json"
    good = MagicMock()
    good.text = json.dumps(_consolidated_response())
    tagging = MagicMock()
    tagging.text = json.dumps(_tagging_response())

    client = MagicMock()
    client.models.generate_content = AsyncMock(side_effect=[bad, good, tagging])
    factory = MagicMock(return_value=client)

    with patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory):
        result = await ActivityEnvironment().run(
            consolidate_video_segments_activity, _inputs(), _raw_segments(), "trace"
        )

    # 2 attempts for consolidation + 1 for tagging
    assert client.models.generate_content.await_count == 3
    assert len(result["consolidated_analysis"].segments) == 2


@pytest.mark.parametrize(
    "team_taxonomy,llm_custom,expected",
    [
        ({"insight_creation": "..."}, ["insight_creation", "hallucinated"], ["insight_creation"]),
        (None, ["insight_creation"], []),
        ({"insight_creation": "..."}, [], []),
    ],
)
def test_validate_tagging_output_drops_custom_tags_not_in_team_taxonomy(team_taxonomy, llm_custom, expected):
    output = SessionTaggingOutput(
        tags_fixed=["onboarding"], tags_custom=llm_custom, tags_freeform=["dashboard"], highlighted=False
    )
    result = _validate_tagging_output(output, custom_tags=team_taxonomy)
    assert result.tags_custom == expected


@pytest.mark.asyncio
async def test_transient_failures_during_consolidation_skip_inner_retry_loop():
    # A 503 from the first consolidation generate_content call should propagate straight
    # out as a retryable ApplicationError — not get swallowed by the parse-retry loop
    # (which would pollute the prompt with HTTP error text).
    server_error = genai_errors.ServerError(
        code=503,
        response_json={"error": {"code": 503, "status": "UNAVAILABLE", "message": "high demand"}},
    )

    client = MagicMock()
    client.models.generate_content = AsyncMock(side_effect=server_error)
    factory = MagicMock(return_value=client)

    with patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory):
        with pytest.raises(ApplicationError) as exc_info:
            await ActivityEnvironment().run(consolidate_video_segments_activity, _inputs(), _raw_segments(), "trace")

    assert exc_info.value.type == "GeminiTransientError"
    # Should fail fast — not exhaust the inner 3-attempt parse-retry loop.
    assert client.models.generate_content.await_count == 1


@pytest.mark.parametrize(
    "transient_exc_factory",
    [
        # Gemini server-side 503 from the tagging follow-up turn
        lambda: genai_errors.ServerError(
            code=503,
            response_json={"error": {"code": 503, "status": "UNAVAILABLE", "message": "service unavailable"}},
        ),
        # aiohttp transport error from generate_content (e.g. tagging follow-up)
        lambda: aiohttp.ServerDisconnectedError("server disconnected"),
    ],
)
@pytest.mark.asyncio
async def test_transient_failures_during_tagging_are_reclassified_as_retryable(transient_exc_factory):
    # Consolidation succeeds, tagging fails with a transient Gemini error.
    consolidation_resp = MagicMock()
    consolidation_resp.text = json.dumps(_consolidated_response())

    client = MagicMock()
    client.models.generate_content = AsyncMock(side_effect=[consolidation_resp, transient_exc_factory()])
    factory = MagicMock(return_value=client)

    with patch(f"{ACTIVITY_MODULE}.genai.AsyncClient", new=factory):
        with pytest.raises(ApplicationError) as exc_info:
            await ActivityEnvironment().run(consolidate_video_segments_activity, _inputs(), _raw_segments(), "trace")

    assert exc_info.value.type == "GeminiTransientError"
    assert exc_info.value.non_retryable is False
