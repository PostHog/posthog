"""URL routes for ci_monitoring."""

from rest_framework.routers import DefaultRouter

from .views import CIRunViewSet, QuarantineViewSet, RepoViewSet, TestCaseViewSet

router = DefaultRouter()
router.register(r"repos", RepoViewSet, basename="ci_monitoring_repos")
router.register(r"runs", CIRunViewSet, basename="ci_monitoring_runs")
router.register(r"tests", TestCaseViewSet, basename="ci_monitoring_tests")
router.register(r"quarantines", QuarantineViewSet, basename="ci_monitoring_quarantines")

urlpatterns = router.urls
