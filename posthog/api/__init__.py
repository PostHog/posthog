from rest_framework import routers

from posthog.ee import check_ee_enabled

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

router = routers.DefaultRouter()

# TODO: add other checks necessary for using EE code
if check_ee_enabled():
    try:
        from ee.clickhouse.views import ClickhouseActions, ClickhouseEvents, ClickhouseInsights, ClickhousePerson

        # router.register(r"action", ClickhouseActions, basename="action")
        # router.register(r"event", ClickhouseEvents, basename="event")
        # router.register(r"insight", ClickhouseInsights, basename="insight")
        # router.register(r"person", ClickhousePerson, basename="person")

    except ImportError:
        print("Clickhouse enabled but missing enterprise capabilities. Defaulting to postgres")

router.register(r"action", action.ActionViewSet)
router.register(r"event", event.EventViewSet)
router.register(r"person", person.PersonViewSet)

router.register(r"annotation", annotation.AnnotationsViewSet)
router.register(r"element", element.ElementViewSet)
router.register(r"feature_flag", feature_flag.FeatureFlagViewSet)
router.register(r"funnel", funnel.FunnelViewSet)
router.register(r"dashboard", dashboard.DashboardsViewSet)
router.register(r"dashboard_item", dashboard.DashboardItemsViewSet)
router.register(r"cohort", cohort.CohortViewSet)
router.register(r"paths", paths.PathsViewSet, basename="paths")
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, basename="personal_api_keys")
router.register(r"team/user", team_user.TeamUserViewSet)
router.register(r"insight", insight.InsightViewSet)
