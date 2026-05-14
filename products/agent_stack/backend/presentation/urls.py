"""URL routes for agent_stack."""

from rest_framework.routers import DefaultRouter

from .views import SplineReticulatorViewSet

router = DefaultRouter()
router.register(r"spline_reticulators", SplineReticulatorViewSet, basename="spline_reticulators")
urlpatterns = router.urls
