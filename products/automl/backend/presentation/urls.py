"""URL routes for AutoML.

Real wiring lives in ``posthog/api/__init__.py`` (nested router). This flat
``DefaultRouter`` is kept as a documentation/reference of the registered
viewsets and isn't imported anywhere.
"""

from rest_framework.routers import DefaultRouter

from .views import AutoMLPipelineViewSet

router = DefaultRouter()
router.register(r"automl_pipelines", AutoMLPipelineViewSet, basename="automl_pipelines")

urlpatterns = router.urls
