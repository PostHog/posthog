import datetime as dt

from rest_framework import request, response, viewsets
from rest_framework.exceptions import (
    ValidationError,
)
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.logging.log_entry import LogEntry, LogEntryLevel, fetch_log_entries
from posthog.warehouse.models.external_data_job import ExternalDataJob
from rest_framework import serializers


class ExternalDataSchemaLogEntrySerializer(DataclassSerializer):
    external_data_schema_id = serializers.CharField(source="log_source_id")

    class Meta:
        dataclass = LogEntry


class ExternalDataSchemaLogViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "external_data_job"
    serializer_class = ExternalDataSchemaLogEntrySerializer

    def list(self, request: request.Request, *args, **kwargs):
        limit_raw = request.GET.get("limit")
        limit: int | None
        if limit_raw:
            try:
                limit = int(limit_raw)
            except ValueError:
                raise ValidationError("Query param limit must be omitted or an integer!")
        else:
            limit = None

        after_raw: str | None = request.GET.get("after")
        after: dt.datetime | None = None
        if after_raw is not None:
            after = dt.datetime.fromisoformat(after_raw.replace("Z", "+00:00"))

        before_raw: str | None = request.GET.get("before")
        before: dt.datetime | None = None
        if before_raw is not None:
            before = dt.datetime.fromisoformat(before_raw.replace("Z", "+00:00"))

        level_filter = [LogEntryLevel[t.upper()] for t in (request.GET.getlist("level_filter", []))]

        latest_job = ExternalDataJob.objects.filter(
            team_id=self.team_id, schema_id=self.parents_query_dict["external_data_schema_id"]
        ).latest("created_at")

        data = fetch_log_entries(
            team_id=self.team_id,
            log_source_id=self.parents_query_dict["external_data_schema_id"],
            run_id=str(latest_job.pk),
            after=after,
            before=before,
            search=request.GET.get("search"),
            limit=limit,
            level_filter=level_filter,
        )

        page = self.paginate_queryset(data)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(data, many=True)
        return response.Response(serializer.data)
