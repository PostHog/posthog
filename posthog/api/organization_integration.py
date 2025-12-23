from rest_framework import mixins, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.organization_integration import OrganizationIntegration


class OrganizationIntegrationSerializer(serializers.ModelSerializer):
    """Serializer for organization-level integrations."""

    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = OrganizationIntegration
        fields = [
            "id",
            "kind",
            "integration_id",
            "config",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by"]


class OrganizationIntegrationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for organization-level integrations.

    Provides read-only access to integrations that are scoped to the entire organization
    (vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.

    Currently only supports listing and deleting. Creation is handled by the integration
    installation flows (e.g., Vercel marketplace installation).
    """

    scope_object = "organization_integration"
    queryset = OrganizationIntegration.objects.select_related("created_by").all()
    serializer_class = OrganizationIntegrationSerializer

    def list(self, request: Request, *args, **kwargs) -> Response:
        """List all organization integrations for the current organization."""
        return super().list(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        """
        Delete an organization integration.

        NOTE: For Vercel integrations, this should trigger billing cancellation.
        This is handled in the model's delete() method or via signals.
        """
        return super().destroy(request, *args, **kwargs)
