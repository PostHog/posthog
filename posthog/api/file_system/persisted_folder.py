from typing import Any

from django.db.models import QuerySet
from django.db.models.functions import Lower

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.file_system.persisted_folder import PersistedFolder


class PersistedFolderSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersistedFolder
        fields = [
            "id",
            "type",
            "protocol",
            "path",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def update(self, instance: PersistedFolder, validated_data: dict[str, Any]) -> PersistedFolder:  # noqa: D401
        validated_data["team_id"] = self.context["team_id"]
        validated_data["user"] = self.context["request"].user
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any]) -> PersistedFolder:  # noqa: D401
        team = self.context["get_team"]()
        user = self.context["request"].user

        obj, _ = PersistedFolder.objects.update_or_create(
            team=team,
            user=user,
            type=validated_data["type"],
            defaults={
                "protocol": validated_data.get("protocol", "products://"),
                "path": validated_data.get("path", ""),
            },
        )

        return obj


class PersistedFolderViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = PersistedFolder.objects.all()
    scope_object = "persisted_folder"
    serializer_class = PersistedFolderSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:  # noqa: D401
        return queryset.filter(team=self.team, user=self.request.user).order_by(Lower("type"))
