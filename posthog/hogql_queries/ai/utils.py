from abc import ABC
from datetime import datetime
from typing import Any, Optional

import orjson

from posthog.caching.utils import ThresholdMode, is_stale

# Mapping from ai_events dedicated columns to their original property names.
# These are stripped from the properties JSON by the MV and stored in dedicated columns.
# Derived from AI_PROPERTY_TO_COLUMN to avoid drift between the two mappings.
from posthog.hogql_queries.ai.ai_property_rewriter import AI_PROPERTY_TO_COLUMN
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
    try:
        props: dict[str, Any] = orjson.loads(properties_json) if properties_json else {}
    except (orjson.JSONDecodeError, TypeError):
        props = {}
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
