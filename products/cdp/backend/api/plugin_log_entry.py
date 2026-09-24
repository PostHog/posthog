from datetime import datetime
from typing import Optional

from rest_framework import exceptions, viewsets
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.cdp.backend.api.plugin import PluginsAccessLevelPermission
from products.cdp.backend.models.plugin import PluginLogEntry, PluginLogEntryType, fetch_plugin_log_entries


class PluginLogEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = PluginLogEntry


class PluginLogEntryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "plugin"
    serializer_class = PluginLogEntrySerializer
    permission_classes = [PluginsAccessLevelPermission]

    @staticmethod
    def _parse_count_param(request, name: str) -> Optional[int]:
        raw = request.GET.get(name)
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            raise exceptions.ValidationError(f"Query param {name} must be omitted or an integer!")
        if value < 0:
            raise exceptions.ValidationError(f"Query param {name} must not be negative!")
        return value

    def list(self, request, *args, **kwargs):
        limit = self._parse_count_param(request, "limit")
        offset = self._parse_count_param(request, "offset") or 0

        after_raw: Optional[str] = request.GET.get("after")
        after: Optional[datetime] = None
        if after_raw is not None:
            after = datetime.fromisoformat(after_raw.replace("Z", "+00:00"))

        before_raw: Optional[str] = request.GET.get("before")
        before: Optional[datetime] = None
        if before_raw is not None:
            before = datetime.fromisoformat(before_raw.replace("Z", "+00:00"))

        page_size = limit if limit is not None else getattr(self.paginator, "default_limit", None)
        # The paginator slices this list, so ClickHouse must return every row up to the end of the
        # requested page. The extra row tells the paginator that a next page exists.
        fetch_limit = offset + page_size + 1 if page_size is not None else None

        type_filter = [PluginLogEntryType[t] for t in (request.GET.getlist("type_filter", []))]
        data = fetch_plugin_log_entries(
            team_id=self.team_id,
            plugin_config_id=self.parents_query_dict["plugin_config_id"],
            after=after,
            before=before,
            search=request.GET.get("search"),
            limit=fetch_limit,
            type_filter=type_filter,
        )

        page = self.paginate_queryset(data)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(data, many=True)
        return Response(serializer.data)
