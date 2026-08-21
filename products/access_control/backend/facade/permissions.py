"""DRF enforcement point for the access-control policies this product owns.

`TeamAndOrgViewSetMixin.get_permissions` puts `SurfaceAccessLimitPermission` into every viewset's stack.
A new endpoint gets surface-limit enforcement automatically. DRF combines
permission classes with AND semantics, so this class is an independent vote. Another class's
internal early return cannot bypass it: a `*`-scoped token that passes `APIScopePermission` is
still limited here.
"""

from typing import Any

from posthog.permissions import ScopeBasePermission, get_organization_from_view

from products.access_control.backend.facade.surface_limits import classify_surface, limit_denial_for_request
from products.access_control.backend.models import SurfaceAccessLimit


class SurfaceAccessLimitPermission(ScopeBasePermission):
    """Denies actions that exceed the organization's limit for the request's access surface.

    This class subclasses ScopeBasePermission only for `_get_required_scopes`. It derives an
    action's read or write nature the same way `APIScopePermission` does, so the two cannot
    disagree about what counts as a write."""

    def has_permission(self, request: Any, view: Any) -> bool:
        # Cheap exit first: almost every request has no classified surface. Classification
        # is two isinstance checks and no query.
        if classify_surface(request) is None:
            return True

        scope_object = getattr(view, "scope_object", None)
        if scope_object is None:
            return True
        try:
            organization = get_organization_from_view(view)
        except ValueError:
            return True

        required_scopes = self._get_required_scopes(request, view) or []
        denial = limit_denial_for_request(
            request,
            organization,
            resource=scope_object if scope_object != "INTERNAL" else SurfaceAccessLimit.ALL_RESOURCES,
            writes=any(scope.endswith(":write") for scope in required_scopes),
        )
        if denial is not None:
            self.message = denial
            return False
        return True
