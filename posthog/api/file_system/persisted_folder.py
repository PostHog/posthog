from typing import Any

from django.db import IntegrityError
from django.db.models import QuerySet
from django.db.models.functions import Lower

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
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
        extra_kwargs = {
            "type": {"help_text": "Which persisted folder this is for the user (home, pinned, custom_products)."},
            "protocol": {"help_text": "Protocol prefix of the folder location, e.g. 'products://'."},
            "path": {"help_text": "Path within the protocol that the folder resolves to."},
        }

    def update(self, instance: PersistedFolder, validated_data: dict[str, Any]) -> PersistedFolder:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["user"] = self.context["request"].user
        return super().update(instance, validated_data)

    def create(self, validated_data: dict[str, Any]) -> PersistedFolder:
        team = self.context["get_team"]()
        user = self.context["request"].user
        surface = self.context.get("file_system_surface", DEFAULT_SURFACE)
        folder_type = validated_data["type"]
        defaults = {
            "protocol": validated_data.get("protocol", "products://"),
            "path": validated_data.get("path", ""),
        }

        # surface_q (not a plain surface=) so an existing legacy NULL row is matched and updated
        # rather than colliding with a new explicit-surface row under the coalescing unique index.
        existing = PersistedFolder.objects.filter(surface_q(surface), team=team, user=user, type=folder_type).first()
        if existing is not None:
            return self._apply_defaults(existing, defaults)

        try:
            return PersistedFolder.objects.create(team=team, user=user, type=folder_type, surface=surface, **defaults)
        except IntegrityError:
            # Lost a race with a concurrent create; fetch the winner and update it instead.
            existing = PersistedFolder.objects.filter(
                surface_q(surface), team=team, user=user, type=folder_type
            ).first()
            if existing is None:
                raise
            return self._apply_defaults(existing, defaults)

    @staticmethod
    def _apply_defaults(instance: PersistedFolder, defaults: dict[str, Any]) -> PersistedFolder:
        instance.protocol = defaults["protocol"]
        instance.path = defaults["path"]
        instance.save(update_fields=["protocol", "path", "updated_at"])
        return instance


@extend_schema(extensions={"x-product": "core"})
class PersistedFolderViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = PersistedFolder.objects.all()
    scope_object = "persisted_folder"
    serializer_class = PersistedFolderSerializer
    # Product surface these folders serve. Subclass and override to expose a different surface
    # (e.g. "desktop") on its own route. The default surface also matches legacy NULL rows.
    file_system_surface: str = DEFAULT_SURFACE

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["file_system_surface"] = self.file_system_surface
        return context

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(surface_q(self.file_system_surface), team=self.team, user=self.request.user).order_by(
            Lower("type")
        )


@extend_schema(extensions={"x-product": "core"})
class DesktopPersistedFolderViewSet(PersistedFolderViewSet):
    """
    Persisted folders for the desktop product surface. Reuses all PersistedFolderViewSet behaviour
    but is scoped to the "desktop" surface, so its folders are fully isolated from the default
    "web" surface.
    """

    file_system_surface = "desktop"
