from abc import ABC
from datetime import datetime
from typing import Any, Optional, cast

import orjson

from posthog.schema import LLMTrace, LLMTraceEvent

from posthog.caching.utils import ThresholdMode, is_stale
from posthog.models.team.team import Team

# Mapping from ai_events dedicated columns to their original property names.
# These are stripped from the properties JSON by the MV and stored in dedicated columns.
HEAVY_COLUMN_TO_PROPERTY: dict[str, str] = {
    "input": "$ai_input",
    "output": "$ai_output",
    "output_choices": "$ai_output_choices",
    "input_state": "$ai_input_state",
    "output_state": "$ai_output_state",
    "tools": "$ai_tools",
}


def merge_heavy_properties(
    properties_json: str,
    heavy_columns: dict[str, str],
) -> dict[str, Any]:
    """Take an ai_events row's properties JSON and heavy column values, return a complete properties dict.

    The ai_events MV strips heavy properties from the JSON blob and stores them
    in dedicated columns. This function merges them back so consumers get a
    complete event.

    ``heavy_columns`` maps column name → raw string value (as returned by
    ClickHouse).  Empty strings are skipped (the column default when the
    property was absent).
    """
    props: dict[str, Any] = orjson.loads(properties_json) if properties_json else {}
    for column_name, raw_value in heavy_columns.items():
        if not raw_value:
            continue
        prop_key = HEAVY_COLUMN_TO_PROPERTY.get(column_name)
        if prop_key is None:
            continue
        try:
            props[prop_key] = orjson.loads(raw_value)
        except (orjson.JSONDecodeError, TypeError):
            props[prop_key] = raw_value
    return props


class TaxonomyCacheMixin(ABC):
    team: Team

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        """
        Despite the lazy mode, it caches for an hour by default. We don't want frequent updates here.
        """
        return is_stale(self.team, date_to=None, interval=None, last_refresh=last_refresh, mode=ThresholdMode.AI)

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        return None


class TraceMapperMixin:
    """Shared mapping logic for TraceQueryRunner and TracesQueryRunner."""

    TRACE_FIELDS_MAPPING: dict[str, str] = {
        "id": "id",
        "ai_session_id": "aiSessionId",
        "created_at": "createdAt",
        "first_distinct_id": "distinctId",
        "total_latency": "totalLatency",
        "input_state_parsed": "inputState",
        "output_state_parsed": "outputState",
        "input_tokens": "inputTokens",
        "output_tokens": "outputTokens",
        "input_cost": "inputCost",
        "output_cost": "outputCost",
        "total_cost": "totalCost",
        "events": "events",
        "trace_name": "traceName",
    }

    def _map_event(self, event_tuple: tuple) -> LLMTraceEvent:
        event_uuid, event_name, event_timestamp, event_properties, *heavy = event_tuple
        heavy_columns = dict(zip(("input", "output", "output_choices", "input_state", "output_state", "tools"), heavy))
        generation: dict[str, Any] = {
            "id": str(event_uuid),
            "event": event_name,
            "createdAt": event_timestamp.isoformat(),
            "properties": merge_heavy_properties(event_properties, heavy_columns),
        }
        return LLMTraceEvent.model_validate(generation)

    def _map_trace(self, result: dict[str, Any], created_at: datetime) -> LLMTrace:
        generations = []
        for event_tuple in result["events"]:
            generations.append(self._map_event(event_tuple))

        trace_dict = {
            **result,
            "created_at": created_at.isoformat(),
            "events": generations,
        }
        for raw_key, parsed_key in [("input_state", "input_state_parsed"), ("output_state", "output_state_parsed")]:
            raw = trace_dict.get(raw_key) or None
            trace_dict[raw_key] = raw
            if raw is not None:
                try:
                    trace_dict[parsed_key] = orjson.loads(raw)
                except (TypeError, orjson.JSONDecodeError):
                    trace_dict[parsed_key] = raw
        trace = LLMTrace.model_validate(
            {
                self.TRACE_FIELDS_MAPPING[key]: value
                for key, value in trace_dict.items()
                if key in self.TRACE_FIELDS_MAPPING
            }
        )
        return trace

    def _map_results(self, columns: list[str], query_results: list) -> list[LLMTrace]:
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        traces = []

        for result in mapped_results:
            timestamp_dt = cast(datetime, result["first_timestamp"])
            if (
                timestamp_dt < self._date_range.date_from_for_filtering()
                or timestamp_dt > self._date_range.date_to_for_filtering()
            ):
                continue

            traces.append(self._map_trace(result, timestamp_dt))

        return traces
