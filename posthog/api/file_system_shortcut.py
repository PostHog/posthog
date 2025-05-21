from typing import Any
from django.db.models import QuerySet
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

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team=self.team, user=self.request.user).order_by(Lower("path"))
