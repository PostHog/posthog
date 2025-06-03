from typing import Any
from django.db.models import QuerySet, Q
from django.db.models.functions import Lower
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut


class FileSystemShortcutSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileSystemShortcut
        fields = [
            "id",
            "path",
            "type",
            "ref",
            "href",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]

    def update(self, instance: FileSystemShortcut, validated_data: dict[str, Any]) -> FileSystemShortcut:
        instance.team_id = self.context["team_id"]
        instance.user = self.context["request"].user
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> FileSystemShortcut:
        request = self.context["request"]
        team = self.context["get_team"]()
        file_system_shortcut = FileSystemShortcut.objects.create(
            team=team,
            user=request.user,
            **validated_data,
        )
        return file_system_shortcut


class FileSystemShortcutViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = FileSystemShortcut.objects.all()
    scope_object = "file_system_shortcut"
    serializer_class = FileSystemShortcutSerializer

    # The request has the team/environment in the URL, but want to filter by project not team.
    param_derived_from_user_current_team = "project_id"
    # This kludge is needed to avoid the default behavior of returning the project_id as the team_id
    _skip_team_id_override_kludge = True

    def _scope_by_team_and_environment(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team__project_id=self.team.project_id)
        queryset = queryset.filter(Q(**self.parent_query_kwargs) | ~Q(type__startswith="hog_function/"))
        return queryset

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return self._scope_by_team_and_environment(queryset).filter(user=self.request.user).order_by(Lower("path"))
