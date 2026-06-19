"""URL routes for field access controls on property definitions."""

from typing import Any

from rest_framework.routers import DefaultRouter, Route
from rest_framework.viewsets import ViewSetMixin

from .views import PropertyAccessControlViewSet


class _CollectionDeleteRouter(DefaultRouter):
    """DefaultRouter that dispatches DELETE on the collection URL and has no detail URL.

    The property access control resource has no detail (pk) URL — rules are
    identified by the (property_definition_id, organization_member, role)
    tuple passed as query parameters. We patch the list route so that DELETE
    on the collection URL is bound to the viewset's ``destroy`` action, and
    drop the default detail route so DRF doesn't auto-expose a duplicate
    ``/{lookup}/`` DELETE — which would otherwise collide with this one in
    the OpenAPI schema.
    """

    _DETAIL_MAPPING = {
        "get": "retrieve",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }

    def get_routes(self, viewset: type[ViewSetMixin]) -> list[Any]:
        routes = super().get_routes(viewset)
        patched: list[Any] = []
        for route in routes:
            if isinstance(route, Route):
                if route.mapping == {"get": "list", "post": "create"}:
                    route = route._replace(mapping={**route.mapping, "delete": "destroy"})
                elif route.mapping == self._DETAIL_MAPPING:
                    # No detail URL — skip the auto-generated /{lookup}/ route.
                    continue
            patched.append(route)
        return patched


router = _CollectionDeleteRouter()
router.register(r"", PropertyAccessControlViewSet, basename="property-access-controls")
urlpatterns = router.urls
