from datetime import datetime
from typing import Optional

from django.utils import timezone

from rest_framework import exceptions, viewsets
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.plugin import PluginsAccessLevelPermission
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.plugin import PluginLogEntry, PluginLogEntryType, fetch_plugin_log_entries


class PluginLogEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = PluginLogEntry


class PluginLogEntryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "plugin"
    serializer_class = PluginLogEntrySerializer
    permission_classes = [PluginsAccessLevelPermission]

    def list(self, request, *args, **kwargs):
        limit_raw = request.GET.get("limit")
        limit: Optional[int]
        if limit_raw:
            try:
                limit = int(limit_raw)
            except ValueError:
                raise exceptions.ValidationError("Query param limit must be omitted or an integer!")
        else:
            limit = None

        after_raw: Optional[str] = request.GET.get("after")
        after: Optional[datetime] = None
        if after_raw is not None:
            after = timezone.datetime.fromisoformat(after_raw.replace("Z", "+00:00"))

        before_raw: Optional[str] = request.GET.get("before")
        before: Optional[datetime] = None
        if before_raw is not None:
            before = timezone.datetime.fromisoformat(before_raw.replace("Z", "+00:00"))

        type_filter = [PluginLogEntryType[t] for t in (request.GET.getlist("type_filter", []))]
        data = fetch_plugin_log_entries(
            team_id=self.team_id,
            plugin_config_id=self.parents_query_dict["plugin_config_id"],
            after=after,
            before=before,
            search=request.GET.get("search"),
            limit=limit,
            type_filter=type_filter,
        )

        page = self.paginate_queryset(data)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(data, many=True)
        return Response(serializer.data)
