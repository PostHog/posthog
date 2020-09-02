from rest_framework import routers

from . import (
    action,
    annotation,
    cohort,
    dashboard,
    element,
    event,
    feature_flag,
    funnel,
    insight,
    paths,
    person,
    personal_api_key,
    team_user,
)


class OptionalTrailingSlashRouter(routers.DefaultRouter):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.trailing_slash = "/?"


router = OptionalTrailingSlashRouter()
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
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, basename="personal_api_keys")
router.register(r"team/user", team_user.TeamUserViewSet)
router.register(r"insight", insight.InsightViewSet)
