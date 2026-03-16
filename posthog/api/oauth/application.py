from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
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
    """Serializer for organization-scoped OAuth applications (read-only)."""

    redirect_uris_list = serializers.SerializerMethodField()

    class Meta:
        model = OAuthApplication
        fields = [
            "id",
            "name",
            "client_id",
            "redirect_uris_list",
            "is_verified",
            "created",
            "updated",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_redirect_uris_list(self, instance: OAuthApplication) -> list[str]:
        return instance.redirect_uris.split() if instance.redirect_uris else []


@extend_schema(tags=["core"])
class OrganizationOAuthApplicationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for listing OAuth applications at the organization level (read-only).
    """

    scope_object = "organization"
    queryset = OAuthApplication.objects.order_by("-created")
    serializer_class = OrganizationOAuthApplicationSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(organization=self.organization)
