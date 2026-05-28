import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.session_summary.activities.video_based.a7d_tag_and_highlight_session import (
    tag_and_highlight_session_activity,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    SessionTaggingOutput,
    VideoSummarySingleSessionInputs,
)

ACTIVITY_MODULE = "posthog.temporal.session_replay.session_summary.activities.video_based.a7d_tag_and_highlight_session"


def _inputs() -> VideoSummarySingleSessionInputs:
    return VideoSummarySingleSessionInputs(
        session_id="sess-1",
        user_id=1,
        team_id=42,
        redis_key_base="test-base",
        model_to_use="test-model",
    )


def _tagging() -> SessionTaggingOutput:
    return SessionTaggingOutput(
        tags_fixed=["onboarding", "search"],
        tags_freeform=["dashboard", "settings"],
        highlighted=True,
    )


def _llm_input() -> MagicMock:
    m = MagicMock()
    m.session_start_time_str = "2024-01-01T12:00:00+00:00"
    m.distinct_id = "user-distinct-id"
    return m


@pytest.mark.asyncio
async def test_skips_kafka_write_when_no_cached_session_data():
    producer = MagicMock()
    with (
        patch(f"{ACTIVITY_MODULE}.get_data_class_from_redis", new=AsyncMock(return_value=None)),
        patch(f"{ACTIVITY_MODULE}.get_producer", return_value=producer),
    ):
        await ActivityEnvironment().run(tag_and_highlight_session_activity, _inputs(), _tagging())

    producer.produce.assert_not_called()


@pytest.mark.asyncio
async def test_produces_tagging_row_to_kafka():
    producer = MagicMock()
    with (
        patch(f"{ACTIVITY_MODULE}.get_data_class_from_redis", new=AsyncMock(return_value=_llm_input())),
        patch(f"{ACTIVITY_MODULE}.get_producer", return_value=producer),
    ):
        await ActivityEnvironment().run(tag_and_highlight_session_activity, _inputs(), _tagging())

    producer.produce.assert_called_once()
    payload = producer.produce.call_args.kwargs["data"]
    assert payload["session_id"] == "sess-1"
    assert payload["team_id"] == 42
    assert payload["ai_tags_fixed"] == ["onboarding", "search"]
    assert payload["ai_tags_freeform"] == ["dashboard", "settings"]
    assert payload["ai_highlighted"] == 1
    # All "identity" fields preserve existing aggregates — see _produce_to_kafka docstring.
    assert payload["click_count"] == 0
    assert payload["block_url"] is None


@pytest.mark.asyncio
async def test_unhighlighted_session_writes_zero():
    producer = MagicMock()
    not_highlighted = SessionTaggingOutput(tags_fixed=[], tags_freeform=[], highlighted=False)
    with (
        patch(f"{ACTIVITY_MODULE}.get_data_class_from_redis", new=AsyncMock(return_value=_llm_input())),
        patch(f"{ACTIVITY_MODULE}.get_producer", return_value=producer),
    ):
        await ActivityEnvironment().run(tag_and_highlight_session_activity, _inputs(), not_highlighted)

    payload = producer.produce.call_args.kwargs["data"]
    assert payload["ai_highlighted"] == 0
