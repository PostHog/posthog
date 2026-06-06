"""URL routes for business_knowledge."""

from rest_framework.routers import DefaultRouter

from .views import KnowledgeSourceViewSet

router = DefaultRouter()
router.register(r"sources", KnowledgeSourceViewSet, basename="knowledge_source")
urlpatterns = router.urls
