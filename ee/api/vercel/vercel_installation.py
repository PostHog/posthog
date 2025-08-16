"""
Implements the Vercel Marketplace API server for managing marketplace installations.

Biggest problem here is that we don't yet conform to Vercel's response schema.

See:
https://vercel.com/docs/integrations/create-integration/marketplace-api
"""

import re
from typing import Any
from rest_framework import serializers, viewsets, exceptions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import BasePermission
from rest_framework import decorators
from rest_framework.views import exception_handler

from ee.api.authentication import VercelAuthentication
from ee.vercel.integration import VercelIntegration


class VercelErrorResponseMixin:
    """
    Mixin that provides custom error response formatting for Vercel API endpoints.
    Transforms standard DRF exceptions into Vercel's error schema format.
    """

    def handle_exception(self, exc):
        """Override DRF's exception handling to return custom Vercel error format"""
        response = exception_handler(exc, self.get_exception_handler_context())

        if response is not None:
            custom_data = self._format_vercel_error(exc, response)
            response.data = custom_data

        return response

    def _format_vercel_error(self, exc, response: Response) -> dict[str, Any]:
        """Format exception into Vercel's custom error schema"""
        message = str(exc.detail) if hasattr(exc, "detail") else str(exc)

        return {"error": {"code": "request_failed", "message": message, "user": {"message": message, "url": None}}}


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


INSTALLATION_ID_PATTERN = re.compile(r"^inst_[A-Za-z0-9]{9,}$")


class VercelInstallationViewSet(VercelErrorResponseMixin, viewsets.GenericViewSet):
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

    def get_object(self):
        from posthog.models.organization_integration import OrganizationIntegration
        from posthog.models.integration import Integration

        installation_id = self.kwargs.get("installation_id")

        if not installation_id:
            raise exceptions.ValidationError({"installation_id": "Missing installation_id in URL."})

        if not INSTALLATION_ID_PATTERN.match(installation_id):
            raise exceptions.ValidationError({"installation_id": "Invalid installation_id format."})

        try:
            installation = OrganizationIntegration.objects.get(
                kind=Integration.IntegrationKind.VERCEL, integration_id=installation_id
            )
            return installation
        except OrganizationIntegration.DoesNotExist:
            raise exceptions.NotFound("Installation not found")

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#upsert-installation
        """
        serializer = UpsertInstallationPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(detail=serializer.errors)

        installation_id = self.kwargs["installation_id"]

        VercelIntegration.upsert_installation(installation_id, serializer.validated_data)
        return Response(status=204)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#get-installation
        """
        installation_id = self.kwargs.get("installation_id", "")

        response_data = VercelIntegration.get_installation(installation_id)
        return Response(response_data, status=200)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#update-installation
        """
        serializer = UpsertInstallationPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(detail=serializer.errors)

        installation_id = self.kwargs["installation_id"]

        VercelIntegration.update_installation(installation_id, serializer.validated_data)
        return Response(status=204)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#delete-installation
        """
        installation_id = self.kwargs["installation_id"]
        response_data = VercelIntegration.delete_installation(installation_id)
        return Response(response_data, status=200)

    @decorators.action(detail=True, methods=["get"])
    def plans(self, _request: Request, *_args: Any, **_kwargs: Any) -> Response:
        """
        Implements: https://vercel.com/docs/integrations/create-integration/marketplace-api#get-installation-plans
        """
        return Response({"plans": VercelIntegration.get_vercel_plans()})


class VercelProductViewSet(VercelErrorResponseMixin, viewsets.GenericViewSet):
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
        product_slug = self.kwargs.get("product_slug", "")
        return Response(VercelIntegration.get_product_plans(product_slug))
