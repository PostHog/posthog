import json

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.session_summary.activities.video_based.a3_slice_session_data_for_segments import (
    slice_session_data_for_segments_activity,
)
from posthog.temporal.session_replay.session_summary.state import StateActivitiesEnum, generate_state_key
from posthog.temporal.session_replay.session_summary.types.video import (
    SegmentLlmContext,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
)

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs


def _make_llm_input() -> SingleSessionSummaryLlmInputs:
    return SingleSessionSummaryLlmInputs(
        session_id="sess-1",
        user_id=1,
        user_distinct_id_to_log="d",
        summary_prompt="",
        system_prompt="",
        simplified_events_mapping={
            # All timestamps relative to session_start_time_str = "2024-01-01T00:00:00Z"
            "evt-a": ["url-a", "win-a", "2024-01-01T00:00:05Z", 0],  # 5s in -> segment 0 (0s-30s)
            "evt-b": ["url-b", "win-b", "2024-01-01T00:00:25Z", 1],  # 25s in -> segment 0
            "evt-c": ["url-c", "win-c", "2024-01-01T00:00:45Z", 2],  # 45s in -> segment 1 (30s-60s)
            "evt-d": ["url-x", "win-x", "2024-01-01T00:01:30Z", 3],  # 90s in -> outside both segments
        },
        event_ids_mapping={"evt-a": "evt-a-full", "evt-b": "evt-b-full", "evt-c": "evt-c-full", "evt-d": "evt-d-full"},
        simplified_events_columns=["$current_url", "$window_id", "timestamp", "event_index"],
        url_mapping_reversed={
            "url-a": "https://app/a",
            "url-b": "https://app/b",
            "url-c": "https://app/c",
            "url-x": "https://app/x",
        },
        window_mapping_reversed={
            "win-a": "window-aaa",
            "win-b": "window-bbb",
            "win-c": "window-ccc",
            "win-x": "window-xxx",
        },
        session_start_time_str="2024-01-01T00:00:00Z",
        session_duration=120,
        distinct_id="d",
        model_to_use="gpt-x",
    )


def _segments() -> list[VideoSegmentSpec]:
    return [
        VideoSegmentSpec(
            segment_index=0,
            start_time=0.0,
            end_time=30.0,
            recording_start_time=0.0,
            recording_end_time=30.0,
        ),
        VideoSegmentSpec(
            segment_index=1,
            start_time=30.0,
            end_time=60.0,
            recording_start_time=30.0,
            recording_end_time=60.0,
        ),
    ]


@pytest.mark.asyncio
async def test_slice_writes_one_redis_key_per_segment_with_filtered_events():
    inputs = VideoSummarySingleSessionInputs(
        session_id="sess-1",
        user_id=1,
        user_distinct_id_to_log="d",
        team_id=1,
        redis_key_base="test-base",
        model_to_use="gpt-x",
    )

    captured: dict[str, str] = {}

    async def _store(*, redis_client, redis_key, data, label):  # noqa: ARG001
        captured[redis_key] = data

    llm_input = _make_llm_input()
    with (
        patch(
            "posthog.temporal.session_replay.session_summary.activities.video_based."
            "a3_slice_session_data_for_segments.get_redis_state_client",
            return_value=(AsyncMock(), "test-base:session_db_data:sess-1", None),
        ),
        patch(
            "posthog.temporal.session_replay.session_summary.activities.video_based."
            "a3_slice_session_data_for_segments.get_data_class_from_redis",
            AsyncMock(return_value=llm_input),
        ),
        patch(
            "posthog.temporal.session_replay.session_summary.activities.video_based."
            "a3_slice_session_data_for_segments.store_data_in_redis",
            new=_store,
        ),
    ):
        await ActivityEnvironment().run(slice_session_data_for_segments_activity, inputs, _segments())

    seg0_key = generate_state_key(
        key_base="test-base",
        label=StateActivitiesEnum.SEGMENT_LLM_CONTEXT,
        state_id="sess-1:0",
    )
    seg1_key = generate_state_key(
        key_base="test-base",
        label=StateActivitiesEnum.SEGMENT_LLM_CONTEXT,
        state_id="sess-1:1",
    )
    assert seg0_key in captured
    assert seg1_key in captured

    seg0 = SegmentLlmContext(**json.loads(captured[seg0_key]))
    seg1 = SegmentLlmContext(**json.loads(captured[seg1_key]))

    # Segment 0 holds events a + b (5s, 25s); segment 1 holds c (45s); evt-d (90s) is outside.
    assert [e.event_id for e in seg0.events] == ["evt-a", "evt-b"]
    assert [e.event_id for e in seg1.events] == ["evt-c"]


@pytest.mark.asyncio
async def test_slice_reduces_url_and_window_maps_to_keys_present_in_slice():
    inputs = VideoSummarySingleSessionInputs(
        session_id="sess-1",
        user_id=1,
        user_distinct_id_to_log="d",
        team_id=1,
        redis_key_base="test-base",
        model_to_use="gpt-x",
    )

    captured: dict[str, str] = {}

    async def _store(*, redis_client, redis_key, data, label):  # noqa: ARG001
        captured[redis_key] = data

    llm_input = _make_llm_input()
    with (
        patch(
            "posthog.temporal.session_replay.session_summary.activities.video_based."
            "a3_slice_session_data_for_segments.get_redis_state_client",
            return_value=(AsyncMock(), "test-base:session_db_data:sess-1", None),
        ),
        patch(
            "posthog.temporal.session_replay.session_summary.activities.video_based."
            "a3_slice_session_data_for_segments.get_data_class_from_redis",
            AsyncMock(return_value=llm_input),
        ),
        patch(
            "posthog.temporal.session_replay.session_summary.activities.video_based."
            "a3_slice_session_data_for_segments.store_data_in_redis",
            new=_store,
        ),
    ):
        await ActivityEnvironment().run(slice_session_data_for_segments_activity, inputs, _segments())

    seg0_key = generate_state_key(
        key_base="test-base",
        label=StateActivitiesEnum.SEGMENT_LLM_CONTEXT,
        state_id="sess-1:0",
    )
    seg0 = SegmentLlmContext(**json.loads(captured[seg0_key]))
    # Only url-a / url-b / win-a / win-b appear in segment 0's events. url-c, url-x, win-c, win-x must not.
    assert set(seg0.url_mapping_reversed.keys()) == {"url-a", "url-b"}
    assert set(seg0.window_mapping_reversed.keys()) == {"win-a", "win-b"}
    assert "url-c" not in seg0.url_mapping_reversed
    assert "url-x" not in seg0.url_mapping_reversed


@pytest.mark.asyncio
async def test_slice_round_trips_through_pydantic():
    seg = SegmentLlmContext(
        events=[],
        simplified_events_columns=["a", "b"],
        url_mapping_reversed={"k": "v"},
        window_mapping_reversed={"k": "v"},
        session_start_time_str="2024-01-01T00:00:00Z",
    )
    encoded = json.dumps(seg.model_dump())
    decoded = SegmentLlmContext(**json.loads(encoded))
    assert decoded == seg
