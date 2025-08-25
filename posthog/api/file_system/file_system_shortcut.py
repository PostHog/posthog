from typing import Any

from django.db.models import Q, QuerySet
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

    def _scope_by_project(self, queryset):
        return queryset.filter(team__project_id=self.team.project_id)

    def _scope_by_project_and_environment(self, queryset: QuerySet) -> QuerySet:
        queryset = self._scope_by_project(queryset)
        # type !~ 'hog_function/.*' or team = $current
        queryset = queryset.filter(Q(**self.parent_query_kwargs) | ~Q(type__startswith="hog_function/"))
        return queryset

    def _filter_queryset_by_parents_lookups(self, queryset):
        return self._scope_by_project(queryset)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return self._scope_by_project_and_environment(queryset).filter(user=self.request.user).order_by(Lower("path"))
