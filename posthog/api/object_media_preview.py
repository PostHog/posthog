from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import TemporaryTokenAuthentication
from posthog.models import EventDefinition, ObjectMediaPreview, UploadedMedia


class ObjectMediaPreviewSerializer(serializers.ModelSerializer):
    media_url = serializers.SerializerMethodField()
    media_type = serializers.SerializerMethodField()
    uploaded_media_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    exported_asset_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    event_definition_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)

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
            "exported_asset_id",
            "event_definition_id",
        )
        read_only_fields = ("id", "created_at", "updated_at", "media_url", "media_type")

    def get_media_url(self, obj: ObjectMediaPreview) -> str:
        return obj.media_url

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
        exported_asset_id = validated_data.pop("exported_asset_id", None)
        event_definition_id = validated_data.pop("event_definition_id", None)

        if bool(uploaded_media_id) + bool(exported_asset_id) != 1:
            raise ValidationError("Exactly one of uploaded_media_id or exported_asset_id must be provided")

        if not event_definition_id:
            raise ValidationError("event_definition_id must be provided")

        uploaded_media = None
        exported_asset = None

        if uploaded_media_id:
            try:
                uploaded_media = UploadedMedia.objects.get(id=uploaded_media_id, team=team)
            except UploadedMedia.DoesNotExist:
                raise ValidationError("Uploaded media not found or does not belong to this team")

        if exported_asset_id:
            from posthog.models.exported_asset import ExportedAsset

            try:
                exported_asset = ExportedAsset.objects.get(id=exported_asset_id, team=team)
            except ExportedAsset.DoesNotExist:
                raise ValidationError("Exported asset not found or does not belong to this team")

        try:
            event_definition = EventDefinition.objects.get(id=event_definition_id, team=team)
        except EventDefinition.DoesNotExist:
            raise ValidationError("Event definition not found or does not belong to this team")

        preview = ObjectMediaPreview.objects.create(
            team=team,
            uploaded_media=uploaded_media,
            exported_asset=exported_asset,
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
    authentication_classes = [TemporaryTokenAuthentication]

    def safely_get_queryset(self, queryset):
        # Filter by event_definition if provided
        event_definition_id = self.request.query_params.get("event_definition")
        if event_definition_id:
            return (
                queryset.filter(event_definition_id=event_definition_id)
                .select_related("uploaded_media", "exported_asset", "event_definition")
                .order_by("-updated_at")
            )

        return queryset.select_related("uploaded_media", "exported_asset", "event_definition").order_by("-updated_at")

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
            .order_by("-updated_at")
            .first()
        )

        if user_uploaded:
            serializer = self.get_serializer(user_uploaded)
            return Response(serializer.data)

        # Fall back to most recent exported asset
        exported = (
            ObjectMediaPreview.objects.filter(
                event_definition_id=event_definition_id,
                team=self.team,
                exported_asset__isnull=False,
            )
            .select_related("exported_asset", "event_definition")
            .order_by("-updated_at")
            .first()
        )

        if exported:
            serializer = self.get_serializer(exported)
            return Response(serializer.data)

        return Response({"detail": "No media preview found"}, status=status.HTTP_404_NOT_FOUND)
