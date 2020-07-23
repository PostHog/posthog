from . import event, person, action, funnel, dashboard, paths, cohort, element, feature_flag, annotation
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r"annotation", annotation.AnnotationsViewSet)
router.register(r"event", event.EventViewSet)
router.register(r"element", element.ElementViewSet)
router.register(r"person", person.PersonViewSet)
router.register(r"action", action.ActionViewSet)
router.register(r"feature_flag", feature_flag.FeatureFlagViewSet)
router.register(r"funnel", funnel.FunnelViewSet)
router.register(r"dashboard", dashboard.DashboardsViewSet)
router.register(r"dashboard_item", dashboard.DashboardItemsViewSet)
router.register(r"cohort", cohort.CohortViewSet)
router.register(r"paths", paths.PathsViewSet, basename="paths")
