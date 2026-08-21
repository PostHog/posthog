"""DRF enforcement point for access-control policies owned by this product.

`TeamAndOrgViewSetMixin.get_permissions` composes `WithinSurfaceLimits` into every viewset's
stack, so a new endpoint gets surface-limit enforcement without knowing limits exist. DRF evaluates
permission classes with AND semantics: this class is an independent vote and cannot be bypassed by
another class's internal early return (a `*`-scoped token passing `APIScopePermission` is still
limited here).
"""

from typing import Any

from posthog.permissions import ScopeBasePermission, get_organization_from_view

from products.access_control.backend.facade.surface_limits import classify_surface, limit_denial_for_request


class WithinSurfaceLimits(ScopeBasePermission):
    """Denies actions that exceed the organization's limit for the request's access surface.

    Subclasses ScopeBasePermission only for `_get_required_scopes`, so this class derives
    an action's read/write nature the same way APIScopePermission does and the two can't
    disagree about what counts as a write."""

    def has_permission(self, request: Any, view: Any) -> bool:
        # Cheap exit first: almost every request has no classified surface, and classification
        # is a couple of isinstance checks with no query.
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
            resource=scope_object if scope_object != "INTERNAL" else None,
            writes=any(scope.endswith(":write") for scope in required_scopes),
        )
        if denial is not None:
            self.message = denial
            return False
        return True
