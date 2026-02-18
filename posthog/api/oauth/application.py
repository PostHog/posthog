from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.oauth import OAuthApplication


class OAuthApplicationPublicMetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = OAuthApplication
        fields = ["name", "client_id", "is_verified"]
        read_only_fields = ["name", "client_id", "is_verified"]


class OAuthApplicationPublicMetadataViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Exposes the public metadata (name, client_id) of an OAuth application,
    identified by its client_id.
    Accessible without authentication.
    """

    queryset = OAuthApplication.objects.all()
    serializer_class = OAuthApplicationPublicMetadataSerializer
    permission_classes = []
    authentication_classes = []
    lookup_field = "client_id"
    lookup_url_kwarg = "client_id"


class OrganizationOAuthApplicationSerializer(serializers.ModelSerializer):
    """Serializer for organization-scoped OAuth applications."""

    created_by = UserBasicSerializer(source="user", read_only=True)
    redirect_uris_list = serializers.ListField(
        child=serializers.URLField(),
        write_only=True,
        required=False,
        help_text="List of redirect URIs",
    )

    class Meta:
        model = OAuthApplication
        fields = [
            "id",
            "name",
            "client_id",
            "client_secret",
            "redirect_uris",
            "redirect_uris_list",
            "is_verified",
            "is_first_party",
            "is_dcr_client",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "client_id",
            "client_secret",
            "is_verified",
            "is_first_party",
            "is_dcr_client",
            "created_at",
            "updated_at",
            "created_by",
        ]
        extra_kwargs = {
            "client_secret": {"write_only": False},
        }

    def to_representation(self, instance: OAuthApplication) -> dict:
        data = super().to_representation(instance)
        data["redirect_uris_list"] = instance.redirect_uris.split() if instance.redirect_uris else []
        if not self.context.get("include_secret", False):
            data.pop("client_secret", None)
        return data

    def validate_redirect_uris_list(self, value: list[str]) -> list[str]:
        return value

    def create(self, validated_data: dict) -> OAuthApplication:
        redirect_uris_list = validated_data.pop("redirect_uris_list", [])
        if redirect_uris_list:
            validated_data["redirect_uris"] = " ".join(redirect_uris_list)

        organization = self.context["get_organization"]()
        user = self.context["request"].user

        validated_data["organization"] = organization
        validated_data["user"] = user
        validated_data["authorization_grant_type"] = OAuthApplication.GRANT_AUTHORIZATION_CODE
        validated_data["client_type"] = OAuthApplication.CLIENT_CONFIDENTIAL
        validated_data["algorithm"] = "RS256"

        try:
            instance = OAuthApplication.objects.create(**validated_data)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict) from e

        return instance

    def update(self, instance: OAuthApplication, validated_data: dict) -> OAuthApplication:
        redirect_uris_list = validated_data.pop("redirect_uris_list", None)
        if redirect_uris_list is not None:
            validated_data["redirect_uris"] = " ".join(redirect_uris_list)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        try:
            instance.save()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict) from e

        return instance


class OrganizationOAuthApplicationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for managing OAuth applications at the organization level.

    Organization admins can create, view, update, and delete OAuth applications
    that are scoped to their organization. These applications can be used by
    third-party integrations to authenticate with PostHog on behalf of users.
    """

    scope_object = "organization"
    queryset = OAuthApplication.objects.select_related("user").order_by("-created_at")
    serializer_class = OrganizationOAuthApplicationSerializer

    def get_queryset(self):
        return super().get_queryset().filter(organization=self.organization)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["include_secret"] = self.action == "create"
        return context

    @action(methods=["POST"], detail=True)
    def rotate_secret(self, request: Request, *args, **kwargs) -> Response:
        """Rotate the client secret for an OAuth application."""
        instance: OAuthApplication = self.get_object()
        from oauth2_provider.generators import generate_client_secret

        instance.client_secret = generate_client_secret()
        instance.save(update_fields=["client_secret"])

        serializer = self.get_serializer(instance)
        data = serializer.data
        data["client_secret"] = instance.client_secret
        return Response(data)
