"""
Implements the Vercel Marketplace API server for managing marketplace installations.

Biggest problem here is that we don't yet conform to Vercel's response schema.

See:
https://vercel.com/docs/integrations/create-integration/marketplace-api
"""

from typing import Any
from django.db import IntegrityError
from rest_framework import serializers, viewsets, exceptions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import mixins
from rest_framework.permissions import BasePermission
from ee.api.authentication import VercelAuthentication
from posthog.event_usage import report_user_signed_up
from posthog.models.user import User
from ee.models.vercel.vercel_installation import VercelInstallation
from rest_framework import decorators


def get_vercel_plans() -> list[dict[str, Any]]:
    """Get PostHog plans formatted for Vercel Marketplace"""
    return [
        {
            "id": "free",
            "type": "subscription",
            "name": "Free",
            "description": "No credit card required",
            "scope": "installation",
            "paymentMethodRequired": False,
            "details": [
                {"label": "Data retention", "value": "1 year"},
                {"label": "Projects", "value": "1"},
                {"label": "Team members", "value": "Unlimited"},
                {"label": "API Access", "value": "✓"},
                {"label": "No limits on tracked users", "value": "✓"},
                {"label": "Community support", "value": "Support via community forum"},
            ],
            "highlightedDetails": [
                {"label": "Feature Flags", "value": "1 million free requests"},
                {"label": "Experiments", "value": "1 million free requests"},
            ],
        },
        {
            "id": "pay_as_you_go",
            "type": "subscription",
            "name": "Pay-as-you-go",
            "description": "Usage-based pricing after free tier",
            "scope": "installation",
            "paymentMethodRequired": True,
            "details": [
                {"label": "Data retention", "value": "7 years"},
                {"label": "Projects", "value": "6"},
                {"label": "Team members", "value": "Unlimited"},
                {"label": "API Access", "value": "✓"},
                {"label": "No limits on tracked users", "value": "✓"},
                {"label": "Standard support", "value": "Support via email, Slack-based over $2k/mo"},
            ],
            "highlightedDetails": [
                {"label": "Feature flags", "value": "1 million requests for free, then from $0.0001/request"},
                {"label": "Experiments", "value": "Billed with feature flags"},
            ],
        },
    ]


class VercelInstallationPermission(BasePermission):
    """
    Custom permission that validates Vercel auth type and installation ID match.
    Vercel auth type is determined by the X-Vercel-Auth header, and can differ per endpoint.
    See Marketplace API spec.
    """

    def has_permission(self, request: Request, view) -> bool:
        self._validate_auth_type_allowed(request, view)
        return True

    def has_object_permission(self, request: Request, view, obj) -> bool:
        self._validate_installation_id_match(request, view)
        return True

    def _get_supported_auth_types(self, view) -> list[str]:
        """
        Get supported auth types for the current action from the viewset.
        Supported auth type is specified by the marketplace API spec.
        """
        return getattr(view, "supported_auth_types", {}).get(view.action, ["User", "System"])

    def _validate_auth_type_allowed(self, request: Request, view) -> None:
        """Validate that the auth type from X-Vercel-Auth header is allowed for this endpoint"""
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()
        if not auth_type:
            raise exceptions.AuthenticationFailed("Missing X-Vercel-Auth header")

        auth_type_title = auth_type.title()
        supported_types = self._get_supported_auth_types(view)

        if auth_type_title not in supported_types:
            raise exceptions.PermissionDenied(
                f"Auth type '{auth_type_title}' not allowed for this endpoint. "
                f"Supported types: {', '.join(supported_types)}"
            )

    def _validate_installation_id_match(self, request: Request, view) -> None:
        """Validate that JWT installation_id matches URL parameter"""
        jwt_payload = self._get_jwt_payload(request)

        # installation_id when going through vercel_installation ViewSet,
        # or parent_lookup_installation_id when going through vercel_resource
        installation_id = view.kwargs.get("installation_id") or view.kwargs.get("parent_lookup_installation_id")

        if jwt_payload.get("installation_id") != installation_id:
            raise exceptions.PermissionDenied("Installation ID mismatch")

    def _get_jwt_payload(self, request: Request) -> dict[str, Any]:
        """Extract JWT payload from authenticated request"""
        if hasattr(request, "auth") and isinstance(request.auth, dict) and request.auth:
            return request.auth
        raise exceptions.AuthenticationFailed("No valid JWT authentication found")


class VercelCredentialsSerializer(serializers.Serializer):
    access_token = serializers.CharField(help_text="Access token authorizes marketplace and integration APIs.")
    token_type = serializers.CharField(help_text="The type of token (default: Bearer).")


class VercelContactSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Contact email address for the account.")
    name = serializers.CharField(required=False, allow_blank=True, help_text="Contact name for the account (optional).")


class VercelAccountSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, help_text="Account name (optional).")
    url = serializers.URLField(help_text="URL of the account.")
    contact = VercelContactSerializer(help_text="Contact information for the account.")


class UpsertInstallationPayloadSerializer(serializers.Serializer):
    scopes = serializers.ListField(
        child=serializers.CharField(), min_length=1, help_text="Array of scopes, must have at least one. Min Length: 1"
    )
    acceptedPolicies = serializers.DictField(
        child=serializers.JSONField(),
        help_text='Policies accepted by the customer. Example: { "toc": "2024-02-28T10:00:00Z" }',
    )
    credentials = VercelCredentialsSerializer(
        help_text="The service-account access token to access marketplace and integration APIs on behalf of a customer's installation."
    )
    account = VercelAccountSerializer(
        help_text="The account information for this installation. Use Get Account Info API to re-fetch this data post installation."
    )


class VercelInstallationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VercelInstallation
        fields = "__all__"


class VercelInstallationViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    queryset = VercelInstallation.objects.all()
    serializer_class = VercelInstallationSerializer
    lookup_field = "installation_id"
    authentication_classes = [VercelAuthentication]
    permission_classes = [VercelInstallationPermission]

    supported_auth_types = {
        "update": ["User"],
        "partial_update": ["User"],
        "destroy": ["User", "System"],
        "retrieve": ["System"],
        "plans": ["System"],
    }

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#upsert-installation
        """
        serializer: UpsertInstallationPayloadSerializer = UpsertInstallationPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(detail=serializer.errors)

        installation_id = self.kwargs["installation_id"]

        try:
            # TODO: Not sure if this is the best move because users might be confused
            # by the default project created here and their "Resource" project.
            organization, _, user = User.objects.bootstrap(
                is_staff=False,
                is_email_verified=True,
                role_at_organization="admin",
                email=serializer.validated_data["account"]["contact"]["email"],
                first_name=serializer.validated_data["account"]["contact"].get("name", ""),
                organization_name=serializer.validated_data["account"].get(
                    "name", f"Vercel Installation {installation_id}"
                ),
                password=None,  # SSO instead of password. Users will still be able to reset their password.
            )
        except IntegrityError:
            raise exceptions.ValidationError(
                {"email": "There is already an account with this email address."},
                code="unique",
            )

        report_user_signed_up(
            user,
            is_instance_first_user=False,
            is_organization_first_user=True,  # Always true because we're always creating a new organization
            backend_processor="VercelInstallationViewSet",
            user_analytics_metadata=user.get_analytics_metadata(),
            org_analytics_metadata=user.organization.get_analytics_metadata() if user.organization else None,
            social_provider="vercel",  # Does this make sense?
        )

        VercelInstallation.objects.create(
            installation_id=installation_id,
            organization=organization,
            upsert_data=serializer.validated_data,
            billing_plan_id="free",  # TODO: Make this dynamic
        )

        # If the provider is using installation-level billing plans,
        # a default plan must be assigned in provider systems (default "free")
        return Response(status=204)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#get-installation
        """

        # Get installation_id from kwargs
        installation_id = self.kwargs.get("installation_id")

        installation = VercelInstallation.objects.get(installation_id=installation_id)

        billing_plans = get_vercel_plans()
        current_plan_id = installation.billing_plan_id

        current_plan = next((plan for plan in billing_plans if plan["id"] == current_plan_id), None)
        response_data = {
            "billingplan": current_plan,
        }
        return Response(response_data, status=200)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#update-installation
        """
        serializer: UpsertInstallationPayloadSerializer = UpsertInstallationPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(detail=serializer.errors)

        installation_id = self.kwargs["installation_id"]

        try:
            installation = VercelInstallation.objects.get(installation_id=installation_id)
        except VercelInstallation.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

        installation.upsert_data = serializer.validated_data
        installation.save(update_fields=["upsert_data"])

        return Response(status=204)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#delete-installation
        """
        return super().destroy(request, *args, **kwargs)

    @decorators.action(detail=True, methods=["get"])
    def plans(self, _request: Request, *_args: Any, **_kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#get-installation-plans
        """
        return Response({"plans": get_vercel_plans()})


class VercelProductViewSet(viewsets.GenericViewSet):
    """
    ViewSet for Vercel product endpoints (/v1/products/{productSlug}/...)
    """

    authentication_classes = [VercelAuthentication]
    permission_classes = [VercelInstallationPermission]
    lookup_field = "product_slug"

    supported_auth_types = {
        "plans": ["User", "System"],
    }

    @decorators.action(detail=True, methods=["get"])
    def plans(self, _request: Request, *_args: Any, **_kwargs: Any) -> Response:
        """
        Get plans for a specific product. Currently only supports 'posthog' as productSlug.
        """
        product_slug = self.kwargs.get("product_slug")
        if product_slug != "posthog":
            raise exceptions.NotFound("Product not found")

        return Response({"plans": get_vercel_plans()})
