import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.pagination import FacadeLimitOffsetPagination
from posthog.api.utils import action
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.paging import Page, PageRequest
from posthog.schema_enums import ProductKey

# Default lookback window applied when the caller does not pass `after`. Bounding the
# query keeps reads on the hot storage tier of `log_entries` (older partitions are
# tiered to object storage); callers can pass an explicit `after` to read further back.
LOG_ENTRIES_DEFAULT_LOOKBACK_DAYS = 7

LOG_SOURCE_TO_PRODUCT_KEY: dict[str, ProductKey] = {
    "hog_function": ProductKey.PIPELINE_DESTINATIONS,
    "hog_flow": ProductKey.WORKFLOWS,
    "batch_exports": ProductKey.PIPELINE_BATCH_EXPORTS,
    "endpoints": ProductKey.ENDPOINTS,
}


@dataclasses.dataclass(frozen=True)
class LogEntry:
    log_source_id: str
    instance_id: str
    timestamp: datetime
    level: str
    message: str


class LogEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = LogEntry


class LogEntryRequestSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False,
        default=50,
        max_value=500,
        min_value=1,
        help_text="Maximum number of log entries to return (1-500, default 50).",
    )
    after = serializers.DateTimeField(
        required=False,
        help_text=(
            "Only return entries after this ISO 8601 timestamp. "
            f"Defaults to {LOG_ENTRIES_DEFAULT_LOOKBACK_DAYS} days ago; pass an explicit value to read further back."
        ),
    )
    before = serializers.DateTimeField(
        required=False,
        help_text="Only return entries before this ISO 8601 timestamp.",
    )
    level = serializers.CharField(
        required=False,
        help_text="Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.",
    )
    search = serializers.CharField(
        required=False,
        help_text="Case-insensitive substring search across log messages.",
    )
    instance_id = serializers.CharField(
        required=False,
        help_text="Filter logs to a specific execution instance.",
    )


class LogEntryPagination(FacadeLimitOffsetPagination):
    # Matches `LogEntryRequestSerializer.limit`, which rejects a limit out of range before the paginator reads it.
    default_limit = 50
    max_limit = 500


def _log_entries_conditions(
    *,
    team_id: int,
    log_source: str,
    log_source_id: str,
    instance_id: Optional[str],
    after: Optional[datetime],
    before: Optional[datetime],
    search: Optional[str],
    level: Optional[list[str]],
) -> tuple[str, dict[str, Any]]:
    if level is None:
        level = []
    clickhouse_where_parts: list[str] = []
    clickhouse_kwargs: dict[str, Any] = {}

    clickhouse_where_parts.append("log_source = %(log_source)s")
    clickhouse_kwargs["log_source"] = log_source
    clickhouse_where_parts.append("log_source_id = %(log_source_id)s")
    clickhouse_kwargs["log_source_id"] = log_source_id
    clickhouse_where_parts.append("team_id = %(team_id)s")
    clickhouse_kwargs["team_id"] = team_id

    if after is None:
        # Always bound the query: unbounded reads scan all partitions, including those
        # tiered to object storage. Anchor the window to `before` when provided so a
        # historical `before` doesn't produce an impossible interval.
        # See LOG_ENTRIES_DEFAULT_LOOKBACK_DAYS.
        after = (before or datetime.now(UTC)) - timedelta(days=LOG_ENTRIES_DEFAULT_LOOKBACK_DAYS)

    if instance_id:
        clickhouse_where_parts.append("instance_id = %(instance_id)s")
        clickhouse_kwargs["instance_id"] = instance_id
    if after:
        clickhouse_where_parts.append("timestamp > toDateTime64(%(after)s, 6)")
        clickhouse_kwargs["after"] = after.isoformat().replace("+00:00", "")
    if before:
        clickhouse_where_parts.append("timestamp < toDateTime64(%(before)s, 6)")
        clickhouse_kwargs["before"] = before.isoformat().replace("+00:00", "")
    if search:
        clickhouse_where_parts.append("message ILIKE %(search)s")
        clickhouse_kwargs["search"] = f"%{search}%"
    if len(level) > 0:
        clickhouse_where_parts.append("upper(level) in %(levels)s")
        clickhouse_kwargs["levels"] = [lev.upper() for lev in level]

    return " AND ".join(clickhouse_where_parts), clickhouse_kwargs


def fetch_log_entries(
    team_id: int,
    log_source: str,
    log_source_id: str,
    limit: int,
    offset: int = 0,
    instance_id: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    search: Optional[str] = None,
    level: Optional[list[str]] = None,
) -> list[Any]:
    """Fetch a list of batch export log entries from ClickHouse."""
    where, clickhouse_kwargs = _log_entries_conditions(
        team_id=team_id,
        log_source=log_source,
        log_source_id=log_source_id,
        instance_id=instance_id,
        after=after,
        before=before,
        search=search,
        level=level,
    )
    clickhouse_kwargs = {**clickhouse_kwargs, "limit": limit, "offset": offset}
    # Entries can share a timestamp. The extra sort terms give them the same order in every query,
    # so a page boundary between them cannot skip or repeat an entry.
    clickhouse_query = f"""
        SELECT log_source_id, instance_id, timestamp, upper(level) as level, message FROM log_entries
        WHERE {where} ORDER BY timestamp DESC, instance_id, message LIMIT %(limit)s OFFSET %(offset)s
    """

    return [LogEntry(*result) for result in cast(list, sync_execute(clickhouse_query, clickhouse_kwargs))]


def count_log_entries(
    team_id: int,
    log_source: str,
    log_source_id: str,
    instance_id: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    search: Optional[str] = None,
    level: Optional[list[str]] = None,
) -> int:
    where, clickhouse_kwargs = _log_entries_conditions(
        team_id=team_id,
        log_source=log_source,
        log_source_id=log_source_id,
        instance_id=instance_id,
        after=after,
        before=before,
        search=search,
        level=level,
    )
    clickhouse_query = f"SELECT count() FROM log_entries WHERE {where}"
    rows = cast(list, sync_execute(clickhouse_query, clickhouse_kwargs))
    return int(rows[0][0])


def log_entries_response(
    view: viewsets.GenericViewSet,
    request: Request,
    *,
    log_source: str,
    log_source_id: str,
    instance_id: Optional[str] = None,
) -> Response:
    """Return one limit/offset page of an object's log entries. The view must page with `LogEntryPagination`."""
    param_serializer = LogEntryRequestSerializer(data=request.query_params)
    if not param_serializer.is_valid():
        raise ValidationError(param_serializer.errors)
    params = param_serializer.validated_data

    filters: dict[str, Any] = {
        "team_id": view.team_id,  # type: ignore[attr-defined]
        "log_source": log_source,
        "log_source_id": log_source_id,
        "instance_id": instance_id or params.get("instance_id"),
        "after": params.get("after"),
        "before": params.get("before"),
        "search": params.get("search"),
        "level": params["level"].split(",") if params.get("level") else None,
    }

    def fetch(page: PageRequest) -> Page[LogEntry]:
        return Page(
            results=fetch_log_entries(**filters, limit=page.limit, offset=page.offset),
            count=count_log_entries(**filters),
        )

    paginator = cast(LogEntryPagination, view.paginator)
    return paginator.get_paginated_facade_response(request, view, fetch, serializer_class=LogEntrySerializer)


class LogEntryMixin(viewsets.GenericViewSet):
    log_source: str  # Should be set by the inheriting class

    def get_log_entry_instance_id(self) -> Optional[str]:
        """
        Can be used overridden to help with getting the instance_id for the log entry.
        Otherwise it defaults to null or the query param if given
        """
        raise NotImplementedError()

    @extend_schema(parameters=[LogEntryRequestSerializer])
    @action(detail=True, methods=["GET"], filter_backends=[], pagination_class=LogEntryPagination)
    def logs(self, request: Request, *args, **kwargs):
        obj = self.get_object()

        if not self.log_source:
            raise ValidationError("log_source not set on the viewset")

        product_key = LOG_SOURCE_TO_PRODUCT_KEY.get(self.log_source, ProductKey.PIPELINE_DESTINATIONS)
        tag_queries(product=product_key, feature=Feature.QUERY)

        try:
            instance_id = self.get_log_entry_instance_id()
        except NotImplementedError:
            instance_id = None

        return log_entries_response(
            self, request, log_source=self.log_source, log_source_id=str(obj.id), instance_id=instance_id
        )
