from typing import Optional

from django.utils import timezone
from rest_framework import exceptions, generics, mixins, request, serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.plugin import PluginOwnershipPermission, PluginsAccessLevelPermission
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.plugin import Plugin, PluginLogEntry, fetch_plugin_log_entries
from posthog.permissions import OrganizationMemberPermissions, ProjectMembershipNecessaryPermissions


class PluginLogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = PluginLogEntry
        fields = ["id", "team_id", "plugin_id", "timestamp", "type", "message", "instance_id"]
        read_only_fields = fields


class PluginLogEntryViewSet(StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Plugin.objects.all()
    serializer_class = PluginLogEntrySerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        OrganizationMemberPermissions,
        PluginsAccessLevelPermission,
        PluginOwnershipPermission,
    ]

    def filter_queryset_by_parents_lookups(self, queryset):
        team_id = self.request.query_params.get("team_id")
        after: Optional[str] = self.request.query_params.get("after")
        if after is not None:
            after = timezone.datetime.fromisoformat(after.replace("Z", "+00:00"))
        before: Optional[str] = self.request.query_params.get("before")
        if before is not None:
            before = timezone.datetime.fromisoformat(before.replace("Z", "+00:00"))
        parents_query_dict = self.get_parents_query_dict()
        return fetch_plugin_log_entries(
            team_id=team_id, plugin_id=parents_query_dict["plugin_id"], after=after, before=before
        )
