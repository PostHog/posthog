import uuid
from collections.abc import Iterable

from django.db.models import QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import ObjectMediaPreview, UploadedMedia
from posthog.models.utils import strict_fetch
from posthog.permissions import is_scout_sandbox_request, scopes_caller_lacks
from posthog.taxonomy.scout_writes import refuse_scout_taxonomy_write

from products.event_definitions.backend.models import EventDefinition
from products.exports.backend.facade.auth import viewable_exported_asset_ids


def with_preview_media(queryset: QuerySet[ObjectMediaPreview]) -> QuerySet[ObjectMediaPreview]:
    # An export's content column can hold the whole file when object storage is off, and no preview path reads it
    return queryset.select_related("uploaded_media", "exported_asset").defer("exported_asset__content")


PREFERRED_EXPORTED_SCAN_LIMIT = 50


def visible_exported_asset_ids(previews: Iterable[ObjectMediaPreview], view: object) -> set[int]:
    """Ids of the exported assets behind these previews that the requesting user may read.

    An exported asset's URL is a long-lived token that works without a session, so it is only handed to
    viewers the exports API would serve the asset to: the user must pass its access checks, and a scoped
    token must hold `export:read`. Without a request user and access control, no exported asset is visible.
    """
    request = getattr(view, "request", None)
    user_access_control = getattr(view, "user_access_control", None)
    user_id = getattr(getattr(request, "user", None), "id", None)
    team_id = getattr(view, "team_id", None)
    asset_ids = {preview.exported_asset_id for preview in previews if preview.exported_asset_id is not None}
    if user_access_control is None or user_id is None or team_id is None or not asset_ids:
        return set()
    if scopes_caller_lacks(request, ["export:read"]):
        return set()
    return viewable_exported_asset_ids(
        asset_ids, team_id=team_id, user_id=user_id, user_access_control=user_access_control
    )


def visible_previews(previews: Iterable[ObjectMediaPreview], view: object) -> list[ObjectMediaPreview]:
    """The previews the requesting user may see, in their original order."""
    previews = list(previews)
    visible_ids = visible_exported_asset_ids(previews, view)
    return [
        preview
        for preview in previews
        if preview.uploaded_media_id or (preview.exported_asset_id and preview.exported_asset_id in visible_ids)
    ]


def _as_uuids(values: Iterable[object]) -> list[uuid.UUID]:
    """The values that parse as UUIDs. A malformed id in the URL then matches nothing instead of raising."""
    parsed = []
    for value in values:
        try:
            parsed.append(uuid.UUID(str(value)))
        except ValueError:
            pass
    return parsed


class ObjectMediaPreviewSerializer(serializers.ModelSerializer):
    media_url = serializers.SerializerMethodField(
        help_text="URL of the preview image. For an exported asset this is a signed link that works without a session."
    )
    media_type = serializers.SerializerMethodField(
        help_text="Where the image comes from: 'uploaded' for user-uploaded media, 'exported' for an exported asset."
    )
    uploaded_media_id = serializers.UUIDField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="ID of uploaded media in this project to use as the preview. Required when creating a preview.",
    )
    event_definition_id = serializers.UUIDField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="ID of the event definition the preview belongs to. Required when creating a preview.",
    )

    class Meta:
        model = ObjectMediaPreview
        fields = (
            "id",
            "created_at",
            "updated_at",
            "media_url",
            "media_type",
            "metadata",
            "uploaded_media_id",
            "event_definition_id",
        )
        read_only_fields = ("id", "created_at", "updated_at", "media_url", "media_type")

    def get_media_url(self, obj: ObjectMediaPreview) -> str:
        if obj.uploaded_media_id:
            return obj.media_url
        # The viewset leaves out previews the viewer may not read and passes the asset ids it allowed. A
        # serializer used without that context therefore returns no long-lived token for an exported asset.
        if obj.exported_asset_id and obj.exported_asset_id in self.context.get("visible_exported_asset_ids", set()):
            return obj.media_url
        return ""

    def get_media_type(self, obj: ObjectMediaPreview) -> str:
        """Return 'uploaded' or 'exported' based on which media is set"""
        if obj.uploaded_media_id:
            return "uploaded"
        elif obj.exported_asset_id:
            return "exported"
        return ""

    def create(self, validated_data):
        team = self.context["get_team"]()

        uploaded_media_id = validated_data.pop("uploaded_media_id", None)
        event_definition_id = validated_data.pop("event_definition_id", None)

        if not uploaded_media_id:
            raise ValidationError("uploaded_media_id must be provided")

        if not event_definition_id:
            raise ValidationError("event_definition_id must be provided")

        try:
            uploaded_media = UploadedMedia.objects.get(id=uploaded_media_id, team=team)
        except UploadedMedia.DoesNotExist:
            raise ValidationError("Uploaded media not found or does not belong to this team")

        try:
            event_definition = EventDefinition.objects.get(id=event_definition_id, team=team)
        except EventDefinition.DoesNotExist:
            raise ValidationError("Event definition not found or does not belong to this team")

        preview = ObjectMediaPreview.objects.create(
            team=team,
            uploaded_media=uploaded_media,
            event_definition=event_definition,
            **validated_data,
        )

        return preview


class ObjectMediaPreviewViewSet(
    TeamAndOrgViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object = "event_definition"
    serializer_class = ObjectMediaPreviewSerializer
    queryset = ObjectMediaPreview.objects.all()

    def check_permissions(self, request: Request) -> None:
        super().check_permissions(request)
        if request.method not in SAFE_METHODS:
            refuse_scout_taxonomy_write(is_scout_sandbox_request(request))

    def safely_get_queryset(self, queryset):
        # The mixin applies its team filter only after this method returns, and the access check below
        # loads every exported preview in the queryset, so scope to the team first.
        queryset = (
            with_preview_media(queryset.filter(team_id=self.team_id))
            .select_related("event_definition")
            .order_by("-updated_at", "-id")
        )
        event_definition_id = self.request.query_params.get("event_definition")
        if self.action == "list" and not event_definition_id:
            raise ValidationError("event_definition query parameter is required")
        if event_definition_id:
            queryset = queryset.filter(event_definition_id=event_definition_id)
        if self.action == "list":
            queryset = strict_fetch(queryset)
        return self._without_hidden_exports(queryset)

    def _without_hidden_exports(self, queryset):
        # Hidden previews are removed from the result, not returned with an empty URL, because their metadata
        # (session id, page URL) is about the recording the viewer may not read.
        exported_previews = queryset.filter(exported_asset__isnull=False)
        if self.kwargs.get("pk"):
            exported_previews = exported_previews.filter(pk__in=_as_uuids([self.kwargs["pk"]]))
        exported = list(exported_previews)
        self._visible_exported_asset_ids = visible_exported_asset_ids(exported, self)
        hidden_ids = [p.id for p in exported if p.exported_asset_id not in self._visible_exported_asset_ids]
        return queryset.exclude(id__in=hidden_ids) if hidden_ids else queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["visible_exported_asset_ids"] = getattr(self, "_visible_exported_asset_ids", set())
        return context

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "event_definition",
                OpenApiTypes.UUID,
                required=True,
                description="ID of the event definition whose previews to list.",
            )
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False, url_path="preferred_for_event")
    def preferred_for_event(self, request, *args, **kwargs):
        """
        Get the preferred media preview for an event definition.
        Most recent user-uploaded, then most recent exported asset.
        Requires event_definition (query param).
        """
        event_definition_id = request.query_params.get("event_definition")
        if not event_definition_id:
            raise ValidationError("event_definition query parameter is required")

        # Try to find most recent user-uploaded media
        user_uploaded = (
            ObjectMediaPreview.objects.filter(
                event_definition_id=event_definition_id,
                team=self.team,
                uploaded_media__isnull=False,
            )
            .select_related("uploaded_media", "event_definition")
            .order_by("-updated_at", "-id")
            .first()
        )

        if user_uploaded:
            serializer = self.get_serializer(user_uploaded)
            return Response(serializer.data)

        exported = list(
            with_preview_media(
                ObjectMediaPreview.objects.filter(
                    event_definition_id=event_definition_id,
                    team=self.team,
                    exported_asset__isnull=False,
                )
            )
            .select_related("event_definition")
            .order_by("-updated_at", "-id")[:PREFERRED_EXPORTED_SCAN_LIMIT]
        )
        self._visible_exported_asset_ids = visible_exported_asset_ids(exported, self)
        preferred = next((p for p in exported if p.exported_asset_id in self._visible_exported_asset_ids), None)

        if preferred:
            return Response(self.get_serializer(preferred).data)

        return Response({"detail": "No media preview found"}, status=status.HTTP_404_NOT_FOUND)
