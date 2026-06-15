import gzip
import json
import base64
import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.schema import ProductKey

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries

FUNCTION_KIND_TO_PRODUCT_KEY: dict[str, ProductKey] = {
    "hog_function": ProductKey.PIPELINE_DESTINATIONS,
    "hog_flow": ProductKey.WORKFLOWS,
}


def tag_invocation_results_query(function_kind: str) -> None:
    product_key = FUNCTION_KIND_TO_PRODUCT_KEY.get(function_kind, ProductKey.PIPELINE_DESTINATIONS)
    tag_queries(product=product_key, feature=Feature.QUERY)


# Per-invocation lifecycle rows (start/finish/retries) collapse to the latest
# `version`. The argMax aliases are deliberately NOT named after their source
# columns: ClickHouse's analyzer resolves a name in WHERE/HAVING to a same-named
# SELECT alias (prefer_column_name_to_alias=0), so reusing e.g. `status` would
# turn `WHERE status = …` into `argMax(status) = …` (aggregate-in-WHERE error).
# We collapse in a subquery, then filter the raw columns in the inner WHERE and
# the aggregated `latest_*` columns in the outer WHERE. Column order is matched
# positionally against HogInvocationResult when building the dataclass.
_COLLAPSED_AGGREGATES = """
    invocation_id,
    argMax(status, version) AS latest_status,
    argMax(error_kind, version) AS latest_error_kind,
    argMax(error_message, version) AS latest_error_message,
    argMax(distinct_id, version) AS latest_distinct_id,
    argMax(person_id, version) AS latest_person_id,
    min(scheduled_at) AS latest_scheduled_at,
    argMax(started_at, version) AS latest_started_at,
    argMax(finished_at, version) AS latest_finished_at,
    argMax(duration_ms, version) AS latest_duration_ms,
    argMax(attempts, version) AS latest_attempts,
    argMax(is_retry, version) AS latest_is_retry,
    argMax(is_deleted, version) AS latest_is_deleted
""".strip()

# Outer projection, in HogInvocationResult field order.
_OUTER_COLUMNS = """
    invocation_id,
    latest_status,
    latest_error_kind,
    latest_error_message,
    latest_distinct_id,
    latest_person_id,
    latest_scheduled_at,
    latest_started_at,
    latest_finished_at,
    latest_duration_ms,
    latest_attempts,
    latest_is_retry
""".strip()


@dataclasses.dataclass(frozen=True)
class HogInvocationResult:
    invocation_id: str
    status: str
    error_kind: str
    error_message: str
    distinct_id: str
    person_id: str
    scheduled_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[int]
    attempts: int
    is_retry: bool


@dataclasses.dataclass(frozen=True)
class HogInvocationResultDetail(HogInvocationResult):
    # The triggering payload (event/person/groups) the run executed against, decoded from the
    # stored gzip+base64 blob into a JSON object so callers get structured data directly. Shape
    # is caller-defined and unbounded.
    invocation_globals: dict[str, Any]


def _decode_invocation_globals(stored: str) -> dict[str, Any]:
    """Decode the stored invocation_globals into a JSON object.

    The producer gzip-compresses then base64-encodes the payload (see the Node
    hog-invocation-results service). Legacy rows predate compression and are stored
    as raw JSON, detected by a leading '{'. A decode failure degrades to an empty
    object so one malformed row can't 500 the whole request.
    """
    if not stored:
        return {}
    try:
        decoded = stored if stored.startswith("{") else gzip.decompress(base64.b64decode(stored)).decode("utf-8")
        parsed = json.loads(decoded)
    except (ValueError, OSError, EOFError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class HogInvocationResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogInvocationResult


@extend_schema_field(OpenApiTypes.OBJECT)
class InvocationGlobalsField(serializers.JSONField):
    pass


class HogInvocationResultDetailSerializer(DataclassSerializer):
    invocation_globals = InvocationGlobalsField(
        help_text="The triggering payload (event/person/groups) the run executed against, as a JSON object."
    )

    class Meta:
        dataclass = HogInvocationResultDetail


class HogInvocationResultsRequestSerializer(serializers.Serializer):
    status = serializers.CharField(
        required=False,
        help_text="Comma-separated invocation statuses to include, e.g. 'failed' or 'success,failed'.",
    )
    distinct_id = serializers.CharField(
        required=False,
        help_text="Only return invocations triggered for this distinct_id (the person the run executed for).",
    )
    after = serializers.CharField(
        required=False,
        default="-7d",
        help_text="Start of the time range, matched on scheduled time. Relative ('-7d', '-24h') or ISO 8601. "
        "Defaults to -7d — bounds the ClickHouse partition scan, so widen it explicitly for older runs.",
    )
    before = serializers.CharField(
        required=False,
        help_text="End of the time range, matched on scheduled time. Same format as 'after'. Defaults to now.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=50,
        max_value=500,
        min_value=1,
        help_text="Maximum number of invocations to return (1-500, default 50).",
    )


def _build_invocation(row: tuple, detail: bool) -> Any:
    common = {
        "invocation_id": row[0],
        "status": row[1],
        "error_kind": row[2],
        "error_message": row[3],
        "distinct_id": row[4],
        "person_id": row[5],
        "scheduled_at": row[6],
        "started_at": row[7],
        "finished_at": row[8],
        "duration_ms": row[9],
        "attempts": row[10],
        "is_retry": bool(row[11]),
    }
    if detail:
        return HogInvocationResultDetail(**common, invocation_globals=_decode_invocation_globals(row[12]))
    return HogInvocationResult(**common)


def fetch_hog_invocation_results(
    team_id: int,
    function_kind: str,
    function_id: str,
    limit: int,
    status: Optional[list[str]] = None,
    distinct_id: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
) -> list[HogInvocationResult]:
    """List a function's invocations, each collapsed to its latest lifecycle state."""
    where = [
        "team_id = %(team_id)s",
        "function_kind = %(function_kind)s",
        "function_id = %(function_id)s",
    ]
    kwargs: dict[str, Any] = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "limit": limit,
    }

    # distinct_id is invocation identity — stable across lifecycle rows — so filter
    # it pre-aggregation on the raw column. status changes start→finish, so it's
    # filtered post-collapse on the aggregated `latest_status` in the outer WHERE.
    if distinct_id:
        where.append("distinct_id = %(distinct_id)s")
        kwargs["distinct_id"] = distinct_id
    # `after`/`before` come in as team-timezone-aware datetimes; convert to UTC before formatting so
    # the naive string matches the UTC `scheduled_at` column (toDateTime64 reads it as UTC). Skipping
    # this shifts the window by the team's offset — wrong for short windows on non-UTC teams.
    if after:
        where.append("scheduled_at >= toDateTime64(%(after)s, 6)")
        kwargs["after"] = after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if before:
        where.append("scheduled_at <= toDateTime64(%(before)s, 6)")
        kwargs["before"] = before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")

    outer_where = ["latest_is_deleted = 0"]
    if status:
        outer_where.append("latest_status IN %(statuses)s")
        kwargs["statuses"] = status

    query = f"""
        SELECT {_OUTER_COLUMNS}
        FROM (
            SELECT {_COLLAPSED_AGGREGATES}
            FROM hog_invocation_results
            WHERE {" AND ".join(where)}
            GROUP BY invocation_id
        )
        WHERE {" AND ".join(outer_where)}
        ORDER BY latest_scheduled_at DESC
        LIMIT %(limit)s
    """

    results = cast(list, sync_execute(query, kwargs))
    return [_build_invocation(row, detail=False) for row in results]


def fetch_hog_invocation_result(
    team_id: int,
    function_kind: str,
    function_id: str,
    invocation_id: str,
) -> Optional[HogInvocationResultDetail]:
    """Fetch a single invocation by id, including its triggering payload."""
    kwargs = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "invocation_id": invocation_id,
    }
    query = f"""
        SELECT {_OUTER_COLUMNS}, latest_invocation_globals
        FROM (
            SELECT {_COLLAPSED_AGGREGATES},
                   argMax(invocation_globals, version) AS latest_invocation_globals
            FROM hog_invocation_results
            WHERE team_id = %(team_id)s
              AND function_kind = %(function_kind)s
              AND function_id = %(function_id)s
              AND invocation_id = %(invocation_id)s
            GROUP BY invocation_id
        )
        WHERE latest_is_deleted = 0
    """

    results = cast(list, sync_execute(query, kwargs))
    if not results:
        return None
    return _build_invocation(results[0], detail=True)
