from typing import Any
from rest_framework.request import Request
from rest_framework.permissions import BasePermission
from rest_framework import exceptions


class VercelPermission(BasePermission):
    """
    Validates Vercel auth type and installation ID match.
    Vercel auth type is determined by the X-Vercel-Auth header, and can differ per endpoint.
    See Marketplace API spec for more details.
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
        Each view can define an attribute like so:
        vercel_supported_auth_types = {
            "list": ["user"],
            ...
            "action_name": ["system"],
        }
        """
        return getattr(view, "vercel_supported_auth_types", {}).get(view.action, ["user", "system"])

    def _validate_auth_type_allowed(self, request: Request, view) -> None:
        """
        Validate that the auth type from X-Vercel-Auth header is allowed for this endpoint.
        Supported auth type is specified by the marketplace API spec.
        """
        auth_type = request.headers.get("X-Vercel-Auth", "").lower()
        if not auth_type:
            raise exceptions.AuthenticationFailed("Missing X-Vercel-Auth header")

        supported_types = self._get_supported_auth_types(view)

        if auth_type not in supported_types:
            raise exceptions.PermissionDenied(
                f"Auth type '{auth_type}' not allowed for this endpoint. "
                f"Supported types: {', '.join(supported_types)}"
            )

    def _validate_installation_id_match(self, request: Request, view) -> None:
        """Validate that JWT installation_id matches URL parameter"""
        jwt_payload = self._get_jwt_payload(request)

        # installation_id when going through the vercel_installation ViewSet,
        # or parent_lookup_installation_id when going through the vercel_resource
        installation_id = view.kwargs.get("installation_id") or view.kwargs.get("parent_lookup_installation_id")

        if jwt_payload.get("installation_id") != installation_id:
            raise exceptions.PermissionDenied("Installation ID mismatch")

    def _get_jwt_payload(self, request: Request) -> dict[str, Any]:
        """Extract JWT payload from authenticated request"""
        if hasattr(request, "auth") and isinstance(request.auth, dict) and request.auth:
            return request.auth
        raise exceptions.AuthenticationFailed("No valid JWT authentication found")
