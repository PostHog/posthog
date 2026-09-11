"""Incremental materialization: its config, its recorded state, and the eligibility check."""

from typing import Any

from rest_framework import serializers

from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle

from products.data_modeling.backend.facade.api import MAX_LOOKBACK_SECONDS


def _clickhouse_types(columns: Any) -> dict[str, str] | None:
    """Pull the ClickHouse type out of each entry in a saved query's stored `columns` blob.

    Only used to spot a nullable unique key, which would silently duplicate rows on every run.
    """
    if not isinstance(columns, dict):
        return None
    types: dict[str, str] = {}
    for name, meta in columns.items():
        if isinstance(meta, dict) and isinstance(meta.get("clickhouse"), str):
            types[name] = meta["clickhouse"]
    return types or None


class IncrementalConfigSerializer(serializers.Serializer):
    """How a view updates its materialized table in place rather than rebuilding it."""

    enabled = serializers.BooleanField(
        default=False, help_text="Whether runs update the table incrementally instead of rebuilding it."
    )
    incremental_key = serializers.CharField(
        help_text="Output column whose advancing value marks rows as new. Each run reads only rows at "
        "or after the last run's highest value for it. When the query groups, this must be one of the "
        "grouped columns, so every group a run touches is recomputed in full.",
    )
    unique_key = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="Output columns that identify a row, used to match recomputed rows against stored "
        "ones. Must include every GROUP BY column. These columns can never be null.",
    )
    lookback_seconds = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        max_value=MAX_LOOKBACK_SECONDS,
        help_text="How far back before the last run's high point to re-read, so late-arriving data is "
        "picked up. Only applies when the incremental key is a date or time.",
    )


class IncrementalStateSerializer(serializers.Serializer):
    """Read-only progress written by the materialization run."""

    watermark = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Highest incremental key value written so far. The next run starts here.",
    )
    definition_fingerprint = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Fingerprint of the query, incremental key, and unique key the stored rows were "
        "built from. When it stops matching, the next run rebuilds the whole table. Lookback is "
        "not part of it: changing lookback never forces a rebuild.",
    )
    last_full_refresh_at = serializers.CharField(
        allow_null=True, required=False, help_text="When the table was last rebuilt from scratch."
    )
    last_run_mode = serializers.ChoiceField(
        choices=[("incremental", "incremental"), ("full_refresh", "full_refresh")],
        allow_null=True,
        required=False,
        help_text="Whether the last run updated the table or rebuilt it.",
    )


class IncrementalEligibilitySerializer(serializers.Serializer):
    """Whether a query can be materialized incrementally, and what stands in the way."""

    eligible = serializers.BooleanField(help_text="True when nothing blocks incremental materialization.")
    key_candidates = serializers.ListField(
        child=serializers.CharField(),
        help_text="Output columns that could be used as the incremental key. Excludes aggregates, "
        "columns whose type cannot serve as an advancing watermark (strings, booleans, arrays), "
        "and for a union only includes columns every branch produces.",
    )
    unique_key_candidates = serializers.ListField(
        child=serializers.CharField(),
        help_text="Output columns the unique key may be built from. A superset of key_candidates: "
        "identifying a row only needs equality, so strings qualify here even though they cannot "
        "be the incremental key.",
    )
    key_candidate_types = serializers.DictField(
        child=serializers.CharField(),
        help_text="Coarse type per candidate, keyed by column name: datetime, date, integer, "
        "decimal, float, string, or uuid. A candidate with no entry has a type the check could "
        "not determine.",
    )
    blockers = serializers.ListField(
        child=serializers.CharField(),
        help_text="Reasons this query cannot be incremental. Each names the construct responsible.",
    )
    warnings = serializers.ListField(
        child=serializers.CharField(),
        help_text="Things that still work but are worth knowing, such as a filter that cannot be "
        "pushed down so each run reads as much data as a full refresh.",
    )


# Same bound other SQL-accepting endpoints put on caller-supplied queries (see
# `posthog/api/query_performance_proxy.py`): parsing runs synchronously on an API worker, so the
# body has to be capped before it reaches the parser.
CHECK_INCREMENTAL_MAX_QUERY_LENGTH = 64 * 1024


class CheckIncrementalThrottle(PersonalApiKeyOrUserRateThrottle):
    """check_incremental parses caller-supplied SQL synchronously on a read scope. The editor calls
    it on a debounce, so a per-caller budget far above typing speed only stops scripted floods of
    large bodies from tying up API workers."""

    scope = "check_incremental"
    rate = "120/minute"


class CheckIncrementalSerializer(serializers.Serializer):
    """Body of the `check_incremental` action: a query and an optional config to check it against."""

    query = serializers.CharField(max_length=CHECK_INCREMENTAL_MAX_QUERY_LENGTH, help_text="The HogQL query to check.")
    incremental_key = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Output column whose advancing value marks rows as new. Omit to only list candidates.",
    )
    unique_key = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Output columns that identify a row. Must include every GROUP BY column.",
    )
    lookback_seconds = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=MAX_LOOKBACK_SECONDS,
        help_text="How far back before the watermark to re-read each run, to pick up late-arriving data.",
    )
