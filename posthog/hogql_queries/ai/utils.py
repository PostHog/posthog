from abc import ABC
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Optional

import orjson

from posthog.schema import PropertyOperator

from posthog.caching.utils import ThresholdMode, is_stale

# Mapping from ai_events dedicated columns to their original property names.
# These are stripped from the properties JSON by the MV and stored in dedicated columns.
# Derived from AI_PROPERTY_TO_COLUMN to avoid drift between the two mappings.
from posthog.hogql_queries.ai.ai_property_rewriter import AI_PROPERTY_TO_COLUMN
from posthog.models.team.team import Team

HEAVY_PROPERTY_NAMES: frozenset[str] = frozenset(
    {
        "$ai_input",
        "$ai_output",
        "$ai_output_choices",
        "$ai_input_state",
        "$ai_output_state",
        "$ai_tools",
    }
)
HEAVY_COLUMN_TO_PROPERTY: dict[str, str] = {
    column_name: property_name
    for property_name, column_name in AI_PROPERTY_TO_COLUMN.items()
    if property_name in HEAVY_PROPERTY_NAMES
}

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


# These operators express the whole condition on their own, so a filter using one is complete without a value.
_VALUELESS_PROPERTY_OPERATORS: frozenset[PropertyOperator] = frozenset(
    {PropertyOperator.IS_SET, PropertyOperator.IS_NOT_SET}
)


def _is_filled_property_filter(prop: Any) -> bool:
    if getattr(prop, "type", None) == "hogql":
        # A HogQL filter carries its whole expression in `key` and has no value.
        return bool(getattr(prop, "key", None))

    if not getattr(prop, "key", None):
        return False

    if getattr(prop, "operator", None) in _VALUELESS_PROPERTY_OPERATORS:
        return True

    value = getattr(prop, "value", None)
    if isinstance(value, list | tuple):
        return len(value) > 0
    # `False`, `0`, and empty strings are real property values, so only a missing value is incomplete here.
    return value is not None


def filled_property_filters(properties: Sequence[Any] | None) -> list[Any]:
    """Drop incomplete filters without conflating valid falsy values with missing input."""
    return [prop for prop in (properties or []) if _is_filled_property_filter(prop)]


def parse_ai_property_value(value: Any) -> Any:
    if value is None or value == "":
        return None

    if isinstance(value, bytes):
        value = value.decode()

    if not isinstance(value, str):
        return value

    try:
        return orjson.loads(value)
    except orjson.JSONDecodeError:
        return value


def parse_ai_properties(properties: Any) -> dict[str, Any]:
    parsed = parse_ai_property_value(properties)
    if not isinstance(parsed, dict):
        return {}

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

    Both source tables return JSON strings at this boundary, so values are decoded exactly once.
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
