"""Test utilities for creating AI events in the ai_events ClickHouse table."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from posthog.clickhouse.client import sync_execute


def bulk_create_ai_events(events: list[dict[str, Any]]) -> None:
    """
    Insert AI events directly into the ai_events ClickHouse table for testing.
    Each event dict should have: event, distinct_id, team (or team_id), properties, timestamp.
    """
    if not events:
        return

    inserts = []
    params: dict[str, Any] = {}

    for index, event_data in enumerate(events):
        timestamp = event_data.get("timestamp") or datetime.now()
        if isinstance(timestamp, str):
            from dateutil.parser import isoparse

            timestamp = isoparse(timestamp)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")

        team_id = event_data.get("team_id") or event_data["team"].pk
        properties = event_data.get("properties", {})
        properties_json = json.dumps(properties)

        event_uuid = str(event_data.get("event_uuid") or uuid.uuid4())
        person_id = str(event_data.get("person_id") or uuid.uuid4())

        inserts.append(
            """(
                %(uuid_{i})s,
                %(event_{i})s,
                %(timestamp_{i})s,
                %(team_id_{i})s,
                %(distinct_id_{i})s,
                %(person_id_{i})s,
                %(properties_{i})s,
                %(trace_id_{i})s,
                %(session_id_{i})s,
                %(parent_id_{i})s,
                %(span_id_{i})s,
                %(span_type_{i})s,
                %(generation_id_{i})s,
                %(span_name_{i})s,
                %(trace_name_{i})s,
                %(prompt_name_{i})s,
                %(model_{i})s,
                %(provider_{i})s,
                %(framework_{i})s,
                %(total_tokens_{i})s,
                %(input_tokens_{i})s,
                %(output_tokens_{i})s,
                %(text_input_tokens_{i})s,
                %(text_output_tokens_{i})s,
                %(image_input_tokens_{i})s,
                %(image_output_tokens_{i})s,
                %(audio_input_tokens_{i})s,
                %(audio_output_tokens_{i})s,
                %(video_input_tokens_{i})s,
                %(video_output_tokens_{i})s,
                %(reasoning_tokens_{i})s,
                %(cache_read_input_tokens_{i})s,
                %(cache_creation_input_tokens_{i})s,
                %(web_search_count_{i})s,
                %(input_cost_usd_{i})s,
                %(output_cost_usd_{i})s,
                %(total_cost_usd_{i})s,
                %(request_cost_usd_{i})s,
                %(web_search_cost_usd_{i})s,
                %(audio_cost_usd_{i})s,
                %(image_cost_usd_{i})s,
                %(video_cost_usd_{i})s,
                %(latency_{i})s,
                %(time_to_first_token_{i})s,
                %(is_error_{i})s,
                %(error_{i})s,
                %(error_type_{i})s,
                %(error_normalized_{i})s,
                %(input_{i})s,
                %(output_{i})s,
                %(output_choices_{i})s,
                %(input_state_{i})s,
                %(output_state_{i})s,
                %(tools_{i})s,
                %(retention_days_{i})s,
                %(_timestamp_{i})s,
                0,
                0
            )""".format(i=index)
        )

        def _prop(name: str, default: Any = "", _props: dict = properties) -> Any:
            return _props.get(name, default)

        def _prop_str(name: str, _props: dict = properties) -> str:
            val = _props.get(name)
            if val is None:
                return ""
            if isinstance(val, (dict, list)):
                return json.dumps(val)
            return str(val)

        params.update(
            {
                f"uuid_{index}": event_uuid,
                f"event_{index}": event_data["event"],
                f"timestamp_{index}": timestamp_str,
                f"team_id_{index}": team_id,
                f"distinct_id_{index}": str(event_data["distinct_id"]),
                f"person_id_{index}": person_id,
                f"properties_{index}": properties_json,
                f"trace_id_{index}": _prop_str("$ai_trace_id"),
                f"session_id_{index}": _prop_str("$ai_session_id"),
                f"parent_id_{index}": _prop_str("$ai_parent_id"),
                f"span_id_{index}": _prop_str("$ai_span_id"),
                f"span_type_{index}": _prop_str("$ai_span_type"),
                f"generation_id_{index}": _prop_str("$ai_generation_id"),
                f"span_name_{index}": _prop_str("$ai_span_name"),
                f"trace_name_{index}": _prop_str("$ai_trace_name"),
                f"prompt_name_{index}": _prop_str("$ai_prompt_name"),
                f"model_{index}": _prop_str("$ai_model"),
                f"provider_{index}": _prop_str("$ai_provider"),
                f"framework_{index}": _prop_str("$ai_framework"),
                f"total_tokens_{index}": int(_prop("$ai_total_tokens", 0) or 0),
                f"input_tokens_{index}": int(_prop("$ai_input_tokens", 0) or 0),
                f"output_tokens_{index}": int(_prop("$ai_output_tokens", 0) or 0),
                f"text_input_tokens_{index}": int(_prop("$ai_text_input_tokens", 0) or 0),
                f"text_output_tokens_{index}": int(_prop("$ai_text_output_tokens", 0) or 0),
                f"image_input_tokens_{index}": int(_prop("$ai_image_input_tokens", 0) or 0),
                f"image_output_tokens_{index}": int(_prop("$ai_image_output_tokens", 0) or 0),
                f"audio_input_tokens_{index}": int(_prop("$ai_audio_input_tokens", 0) or 0),
                f"audio_output_tokens_{index}": int(_prop("$ai_audio_output_tokens", 0) or 0),
                f"video_input_tokens_{index}": int(_prop("$ai_video_input_tokens", 0) or 0),
                f"video_output_tokens_{index}": int(_prop("$ai_video_output_tokens", 0) or 0),
                f"reasoning_tokens_{index}": int(_prop("$ai_reasoning_tokens", 0) or 0),
                f"cache_read_input_tokens_{index}": int(_prop("$ai_cache_read_input_tokens", 0) or 0),
                f"cache_creation_input_tokens_{index}": int(_prop("$ai_cache_creation_input_tokens", 0) or 0),
                f"web_search_count_{index}": int(_prop("$ai_web_search_count", 0) or 0),
                f"input_cost_usd_{index}": float(_prop("$ai_input_cost_usd", 0) or 0),
                f"output_cost_usd_{index}": float(_prop("$ai_output_cost_usd", 0) or 0),
                f"total_cost_usd_{index}": float(_prop("$ai_total_cost_usd", 0) or 0),
                f"request_cost_usd_{index}": float(_prop("$ai_request_cost_usd", 0) or 0),
                f"web_search_cost_usd_{index}": float(_prop("$ai_web_search_cost_usd", 0) or 0),
                f"audio_cost_usd_{index}": float(_prop("$ai_audio_cost_usd", 0) or 0),
                f"image_cost_usd_{index}": float(_prop("$ai_image_cost_usd", 0) or 0),
                f"video_cost_usd_{index}": float(_prop("$ai_video_cost_usd", 0) or 0),
                f"latency_{index}": float(_prop("$ai_latency", 0) or 0),
                f"time_to_first_token_{index}": float(_prop("$ai_time_to_first_token", 0) or 0),
                f"is_error_{index}": 1 if _prop_str("$ai_is_error") == "true" else 0,
                f"error_{index}": _prop_str("$ai_error"),
                f"error_type_{index}": _prop_str("$ai_error_type"),
                f"error_normalized_{index}": _prop_str("$ai_error_normalized"),
                f"input_{index}": _prop_str("$ai_input"),
                f"output_{index}": _prop_str("$ai_output"),
                f"output_choices_{index}": _prop_str("$ai_output_choices"),
                f"input_state_{index}": _prop_str("$ai_input_state"),
                f"output_state_{index}": _prop_str("$ai_output_state"),
                f"tools_{index}": _prop_str("$ai_tools"),
                f"retention_days_{index}": 10000,
                f"_timestamp_{index}": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    query = f"""
        INSERT INTO sharded_ai_events (
            uuid, event, timestamp, team_id, distinct_id, person_id, properties,
            trace_id, session_id, parent_id, span_id, span_type, generation_id,
            span_name, trace_name, prompt_name,
            model, provider, framework,
            total_tokens, input_tokens, output_tokens,
            text_input_tokens, text_output_tokens,
            image_input_tokens, image_output_tokens,
            audio_input_tokens, audio_output_tokens,
            video_input_tokens, video_output_tokens,
            reasoning_tokens, cache_read_input_tokens, cache_creation_input_tokens,
            web_search_count,
            input_cost_usd, output_cost_usd, total_cost_usd,
            request_cost_usd, web_search_cost_usd, audio_cost_usd, image_cost_usd, video_cost_usd,
            latency, time_to_first_token,
            is_error, error, error_type, error_normalized,
            input, output, output_choices, input_state, output_state, tools,
            retention_days,
            _timestamp, _offset, _partition
        ) VALUES {", ".join(inserts)}
    """
    sync_execute(query, params, flush=False)
