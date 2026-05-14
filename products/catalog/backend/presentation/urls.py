"""URL routes for catalog.

Real wiring lives in `posthog/api/__init__.py` (nested under projects_router).
This flat DefaultRouter is kept as a documentation/reference of the
registered viewsets and isn't imported anywhere.
"""

from rest_framework.routers import DefaultRouter

from .views import CatalogColumnViewSet, CatalogMetricViewSet, CatalogNodeViewSet, CatalogRelationshipViewSet

router = DefaultRouter()
router.register(r"catalog/nodes", CatalogNodeViewSet, basename="catalog_nodes")
router.register(r"catalog/columns", CatalogColumnViewSet, basename="catalog_columns")
router.register(r"catalog/relationships", CatalogRelationshipViewSet, basename="catalog_relationships")
router.register(r"catalog/metrics", CatalogMetricViewSet, basename="catalog_metrics")

urlpatterns = router.urls
