import json
from typing import Any, cast

import structlog
import temporalio
from temporalio.exceptions import ApplicationError

from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
    get_redis_state_client,
    store_data_in_redis,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    SegmentEventEntry,
    SegmentLlmContext,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
)

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import calculate_time_since_start, get_column_index, prepare_datetime

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def slice_session_data_for_segments_activity(
    inputs: VideoSummarySingleSessionInputs,
    segment_specs: list[VideoSegmentSpec],
) -> None:
    redis_client, redis_input_key, _ = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        state_id=inputs.session_id,
    )
    llm_input_raw = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_input_key,
        label=StateActivitiesEnum.SESSION_DB_DATA,
        target_class=SingleSessionSummaryLlmInputs,
    )
    if llm_input_raw is None:
        msg = f"No LLM input found in Redis for session {inputs.session_id} when slicing segments"
        temporalio.activity.logger.error(
            msg,
            extra={"session_id": inputs.session_id, "signals_type": "session-summaries"},
        )
        raise ApplicationError(msg, non_retryable=True)
    llm_input = cast(SingleSessionSummaryLlmInputs, llm_input_raw)

    session_start_time = prepare_datetime(llm_input.session_start_time_str)
    timestamp_index = get_column_index(llm_input.simplified_events_columns, "timestamp")
    event_index_index = get_column_index(llm_input.simplified_events_columns, "event_index")
    try:
        current_url_index: int | None = get_column_index(llm_input.simplified_events_columns, "$current_url")
    except ValueError:
        current_url_index = None
    try:
        window_id_index: int | None = get_column_index(llm_input.simplified_events_columns, "$window_id")
    except ValueError:
        window_id_index = None

    # Inclusive bounds — boundary events appear in both segments and are deduped at consolidation.
    indexed_segments = sorted(segment_specs, key=lambda s: s.start_time)
    buckets: dict[int, list[tuple[str, list[Any], int]]] = {s.segment_index: [] for s in indexed_segments}

    for event_id, event_data in llm_input.simplified_events_mapping.items():
        ts = event_data[timestamp_index]
        if not isinstance(ts, str):
            continue
        event_ms = calculate_time_since_start(ts, session_start_time)
        event_index = event_data[event_index_index]
        if not isinstance(event_index, int):
            continue
        widened_data: list[Any] = list(event_data)
        for spec in indexed_segments:
            if int(spec.start_time * 1000) <= event_ms <= int(spec.end_time * 1000):
                buckets[spec.segment_index].append((event_id, widened_data, event_index))

    for spec in segment_specs:
        bucket = buckets[spec.segment_index]
        bucket.sort(key=lambda triple: triple[2])

        url_keys_used: set[str] = set()
        window_keys_used: set[str] = set()
        for _, event_data, _ in bucket:
            if current_url_index is not None and current_url_index < len(event_data):
                value = event_data[current_url_index]
                if isinstance(value, str):
                    url_keys_used.add(value)
            if window_id_index is not None and window_id_index < len(event_data):
                value = event_data[window_id_index]
                if isinstance(value, str):
                    window_keys_used.add(value)

        url_slice = {k: llm_input.url_mapping_reversed[k] for k in url_keys_used if k in llm_input.url_mapping_reversed}
        window_slice = {
            k: llm_input.window_mapping_reversed[k] for k in window_keys_used if k in llm_input.window_mapping_reversed
        }

        context = SegmentLlmContext(
            events=[SegmentEventEntry(event_id=eid, data=data) for eid, data, _ in bucket],
            simplified_events_columns=llm_input.simplified_events_columns,
            url_mapping_reversed=url_slice,
            window_mapping_reversed=window_slice,
            session_start_time_str=llm_input.session_start_time_str,
        )

        segment_state_id = f"{inputs.session_id}:{spec.segment_index}"
        segment_key = generate_state_key(
            key_base=inputs.redis_key_base,
            label=StateActivitiesEnum.SEGMENT_LLM_CONTEXT,
            state_id=segment_state_id,
        )
        await store_data_in_redis(
            redis_client=redis_client,
            redis_key=segment_key,
            data=json.dumps(context.model_dump()),
            label=StateActivitiesEnum.SEGMENT_LLM_CONTEXT,
        )
