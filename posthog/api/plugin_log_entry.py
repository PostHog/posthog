from typing import Optional

from django.utils import timezone
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.plugin import PluginOwnershipPermission, PluginsAccessLevelPermission
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.plugin import PluginLogEntry, fetch_plugin_log_entries
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class PluginLogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = PluginLogEntry
        fields = ["id", "team_id", "plugin_id", "timestamp", "source", "type", "message", "instance_id"]
        read_only_fields = fields


class PluginLogEntryViewSet(StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = PluginLogEntrySerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        PluginsAccessLevelPermission,
        PluginOwnershipPermission,
        TeamMemberAccessPermission,
    ]

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

        parents_query_dict = self.get_parents_query_dict()

        return fetch_plugin_log_entries(
            team_id=parents_query_dict["team_id"],
            plugin_config_id=parents_query_dict["plugin_config_id"],
            after=after,
            before=before,
            search=self.request.GET.get("search"),
            limit=limit,
        )
