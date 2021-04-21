from typing import Optional

from django.utils import timezone
from rest_framework import exceptions, generics, mixins, request, serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.plugin import PluginOwnershipPermission, PluginsAccessLevelPermission
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.plugin import Plugin, PluginLogEntry, fetch_plugin_log_entries
from posthog.models.team import Team
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
        limit = self.request.GET.get("limit")
        if limit:
            try:
                limit = int(limit)
            except ValueError:
                raise exceptions.ValidationError("Query param limit must be omitted or an integer!")
        else:
            limit = None

        team_id = self.request.GET.get("team_id")
        if not team_id:
            raise exceptions.ValidationError("Query param team_id is required!")

        parents_query_dict = self.get_parents_query_dict()

        organization_id = parents_query_dict["organization_id"]
        if not Team.objects.filter(id=team_id, organization_id=organization_id).exists():
            raise exceptions.PermissionDenied(
                f"Project ID {team_id} does not belong to the organization ID {organization_id}!"
            )

        after_raw: Optional[str] = self.request.GET.get("after")
        after: Optional[timezone.datetime] = None
        if after_raw is not None:
            after = timezone.datetime.fromisoformat(after_raw.replace("Z", "+00:00"))

        before_raw: Optional[str] = self.request.GET.get("before")
        before: Optional[timezone.datetime] = None
        if before_raw is not None:
            before = timezone.datetime.fromisoformat(before_raw.replace("Z", "+00:00"))

        return fetch_plugin_log_entries(
            team_id=int(team_id),
            plugin_id=parents_query_dict["plugin_id"],
            after=after,
            before=before,
            search=self.request.GET.get("search"),
            limit=limit,
        )
