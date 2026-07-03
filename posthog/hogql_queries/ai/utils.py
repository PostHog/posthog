from abc import ABC
from datetime import datetime
from typing import Any, Optional

from django.conf import settings

import orjson

from posthog.caching.utils import ThresholdMode, is_stale

# Mapping from ai_events dedicated columns to their original property names.
# These are stripped from the properties JSON by the MV and stored in dedicated columns.
# Derived from AI_PROPERTY_TO_COLUMN to avoid drift between the two mappings.
from posthog.hogql_queries.ai.ai_property_rewriter import AI_PROPERTY_TO_COLUMN
from posthog.models.event.sql import EVENTS_PROPERTIES_JSON_SUBCOLUMNS
from posthog.models.team.team import Team

_HEAVY_PROPERTIES: frozenset[str] = frozenset(
    {
        "$ai_input",
        "$ai_output",
        "$ai_output_choices",
        "$ai_input_state",
        "$ai_output_state",
        "$ai_tools",
    }
)
HEAVY_COLUMN_TO_PROPERTY: dict[str, str] = {v: k for k, v in AI_PROPERTY_TO_COLUMN.items() if k in _HEAVY_PROPERTIES}

# Ordered tuple of heavy column names. Used for unpacking event tuples from ClickHouse.
# Keep in sync with the SQL tuple in trace_query_runner.py _build_query().
HEAVY_COLUMN_NAMES: tuple[str, ...] = tuple(HEAVY_COLUMN_TO_PROPERTY.keys())

_NUMERIC_AI_PROPERTIES: frozenset[str] = frozenset(
    {
        "$ai_http_status",
        "$ai_total_tokens",
        "$ai_input_tokens",
        "$ai_output_tokens",
        "$ai_text_input_tokens",
        "$ai_text_output_tokens",
        "$ai_image_input_tokens",
        "$ai_image_output_tokens",
        "$ai_audio_input_tokens",
        "$ai_audio_output_tokens",
        "$ai_video_input_tokens",
        "$ai_video_output_tokens",
        "$ai_reasoning_tokens",
        "$ai_cache_read_input_tokens",
        "$ai_cache_creation_input_tokens",
        "$ai_web_search_count",
        "$ai_input_cost_usd",
        "$ai_output_cost_usd",
        "$ai_total_cost_usd",
        "$ai_request_cost_usd",
        "$ai_web_search_cost_usd",
        "$ai_audio_cost_usd",
        "$ai_image_cost_usd",
        "$ai_video_cost_usd",
        "$ai_latency",
        "$ai_time_to_first_token",
    }
)


def parse_ai_property_value(value: Any) -> Any:
    if value is None or value == "":
        return None

    if isinstance(value, bytes):
        value = value.decode()

    if not isinstance(value, str):
        return value

    try:
        parsed = orjson.loads(value)
    except orjson.JSONDecodeError:
        return value

    # Reconstructed new-schema blobs can double-encode list elements as JSON strings; legacy
    # blobs must keep list elements exactly as stored.
    if isinstance(parsed, list) and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        return [parse_ai_property_value(item) for item in parsed]

    return parsed


def parse_ai_properties(properties: Any) -> dict[str, Any]:
    parsed = parse_ai_property_value(properties)
    if not isinstance(parsed, dict):
        return {}

    # New-schema blob reconstruction materializes subcolumn keys even when absent from the
    # original event; drop the resulting ""/None placeholders. Legacy blobs only contain keys
    # that were actually ingested, so an empty value there is real data.
    if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        for prop_key in EVENTS_PROPERTIES_JSON_SUBCOLUMNS:
            if parsed.get(prop_key) in ("", None):
                parsed.pop(prop_key, None)

    for prop_key in _NUMERIC_AI_PROPERTIES:
        value = parsed.get(prop_key)
        if isinstance(value, str):
            parsed_value = parse_ai_property_value(value)
            if type(parsed_value) in (int, float):
                parsed[prop_key] = parsed_value

    return parsed


def merge_heavy_properties(
    properties_json: Any,
    heavy_columns: dict[str, Any],
) -> dict[str, Any]:
    """Take an ai_events row's properties JSON and heavy column values, return a complete properties dict.

    The ai_events MV strips heavy properties from the JSON blob and stores them
    in dedicated columns. This function merges them back so consumers get a
    complete event.

    ``heavy_columns`` maps column name → raw string value (as returned by
    ClickHouse).  Empty strings are skipped (the column default when the
    property was absent).
    """
    props = parse_ai_properties(properties_json)
    for column_name, raw_value in heavy_columns.items():
        if not raw_value:
            continue
        prop_key = HEAVY_COLUMN_TO_PROPERTY.get(column_name)
        if prop_key is None:
            continue
        props[prop_key] = parse_ai_property_value(raw_value)
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
