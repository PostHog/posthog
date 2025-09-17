import dataclasses
from datetime import datetime
from typing import Any, Optional, cast

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.utils import action
from posthog.clickhouse.client.execute import sync_execute


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
    limit = serializers.IntegerField(required=False, default=50, max_value=500, min_value=1)
    after = serializers.DateTimeField(required=False)
    before = serializers.DateTimeField(required=False)
    level = serializers.CharField(required=False)
    search = serializers.CharField(required=False)
    instance_id = serializers.CharField(required=False)


def fetch_log_entries(
    team_id: int,
    log_source: str,
    log_source_id: str,
    limit: int,
    instance_id: Optional[str] = None,
    after: Optional[datetime] = None,
    before: Optional[datetime] = None,
    search: Optional[str] = None,
    level: Optional[list[str]] = None,
) -> list[Any]:
    """Fetch a list of batch export log entries from ClickHouse."""
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

    clickhouse_query = f"""
        SELECT log_source_id, instance_id, timestamp, upper(level) as level, message FROM log_entries
        WHERE {' AND '.join(clickhouse_where_parts)} ORDER BY timestamp DESC {f'LIMIT {limit}'}
    """

    return [LogEntry(*result) for result in cast(list, sync_execute(clickhouse_query, clickhouse_kwargs))]


class LogEntryMixin(viewsets.GenericViewSet):
    log_source: str  # Should be set by the inheriting class

    def get_log_entry_instance_id(self) -> Optional[str]:
        """
        Can be used overridden to help with getting the instance_id for the log entry.
        Otherwise it defaults to null or the query param if given
        """
        raise NotImplementedError()

    @action(detail=True, methods=["GET"])
    def logs(self, request: Request, *args, **kwargs):
        obj = self.get_object()

        param_serializer = LogEntryRequestSerializer(data=request.query_params)

        if not self.log_source:
            raise ValidationError("log_source not set on the viewset")

        if not param_serializer.is_valid():
            raise ValidationError(param_serializer.errors)

        params = param_serializer.validated_data

        try:
            instance_id = self.get_log_entry_instance_id()
        except NotImplementedError:
            instance_id = params.get("instance_id")

        data = fetch_log_entries(
            team_id=self.team_id,  # type: ignore
            log_source=self.log_source,
            log_source_id=str(obj.id),
            limit=params["limit"],
            # From request params
            instance_id=instance_id,
            after=params.get("after"),
            before=params.get("before"),
            search=params.get("search"),
            level=params["level"].split(",") if params.get("level") else None,
        )

        page = self.paginate_queryset(data)
        if page is not None:
            serializer = LogEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = LogEntrySerializer(data, many=True)
        return Response({"status": "not implemented"})
