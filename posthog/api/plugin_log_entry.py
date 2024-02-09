from typing import Optional

from django.utils import timezone
from rest_framework import exceptions, mixins, viewsets
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.plugin import PluginOwnershipPermission, PluginsAccessLevelPermission
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.plugin import (
    PluginLogEntry,
    PluginLogEntryType,
    fetch_plugin_log_entries,
)


class PluginLogEntrySerializer(DataclassSerializer):
    class Meta:
        dataclass = PluginLogEntry


class PluginLogEntryViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    base_scope = "plugin"
    serializer_class = PluginLogEntrySerializer
    permission_classes = [PluginsAccessLevelPermission, PluginOwnershipPermission]

    def get_queryset(self):
        limit_raw = self.request.GET.get("limit")
        limit: Optional[int]
        if limit_raw:
            try:
                limit = int(limit_raw)
            except ValueError:
                raise exceptions.ValidationError("Query param limit must be omitted or an integer!")
        else:
            limit = None

        after_raw: Optional[str] = self.request.GET.get("after")
        after: Optional[timezone.datetime] = None
        if after_raw is not None:
            after = timezone.datetime.fromisoformat(after_raw.replace("Z", "+00:00"))

        before_raw: Optional[str] = self.request.GET.get("before")
        before: Optional[timezone.datetime] = None
        if before_raw is not None:
            before = timezone.datetime.fromisoformat(before_raw.replace("Z", "+00:00"))

        type_filter = [PluginLogEntryType[t] for t in (self.request.GET.getlist("type_filter", []))]
        return fetch_plugin_log_entries(
            team_id=self.parents_query_dict["team_id"],
            plugin_config_id=self.parents_query_dict["plugin_config_id"],
            after=after,
            before=before,
            search=self.request.GET.get("search"),
            limit=limit,
            type_filter=type_filter,
        )
