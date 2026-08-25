"""DRF enforcement point for the access-control policies this product owns.

`TeamAndOrgViewSetMixin.get_permissions` puts `MCPAccessPermission` into every viewset's stack.
A new endpoint gets MCP read-only enforcement automatically. DRF combines permission classes
with AND semantics, so this class is an independent vote. Another class's internal early
return cannot bypass it: a `*`-scoped token that passes `APIScopePermission` is still capped
here.
"""

from django.http import HttpRequest

from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.permissions import ScopeBasePermission, get_organization_from_view

from products.access_control.backend.facade.mcp_access import is_mcp_request, mcp_access_denial_for_request


class MCPAccessPermission(ScopeBasePermission):
    """Denies write actions through the MCP server when the organization restricts it.

    This class subclasses ScopeBasePermission only for `_get_required_scopes`. It derives an
    action's read or write nature the same way `APIScopePermission` does, so the two cannot
    disagree about what counts as a write."""

    def has_permission(self, request: HttpRequest | Request, view: APIView) -> bool:
        # Cheap exit first. Almost every request is not MCP. The check is two isinstance
        # checks and one header read, with no query.
        if not is_mcp_request(request):
            return True

        if getattr(view, "scope_object", None) is None:
            return True
        try:
            organization = get_organization_from_view(view)
        except ValueError:
            return True

        required_scopes = self._get_required_scopes(request, view) or []
        denial = mcp_access_denial_for_request(
            request,
            organization,
            writes=any(scope.endswith(":write") for scope in required_scopes),
        )
        if denial is not None:
            self.message = denial
            return False
        return True
