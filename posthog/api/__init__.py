from rest_framework import decorators, exceptions, response, routers

from posthog.ee import check_ee_enabled
from posthog.settings import print_warning
from posthog.version import VERSION

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
        self.trailing_slash = r"/?"


@decorators.api_view(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@decorators.authentication_classes([])
@decorators.permission_classes([])
def api_not_found(request):
    raise exceptions.NotFound(detail="Endpoint not found.")


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

if check_ee_enabled():
    try:
        from ee.clickhouse.views import (  # type: ignore
            ClickhouseActions,
            ClickhouseEvents,
            ClickhouseInsights,
            ClickhousePerson,
        )

        # router.register(r"action", ClickhouseActions, basename="action")
        # router.register(r"event", ClickhouseEvents, basename="event")
        # router.register(r"insight", ClickhouseInsights, basename="insight")
        # router.register(r"person", ClickhousePerson, basename="person")

    except ImportError:
        print_warning(("ClickHouse enabled, but enterprise features missing!", "Defaulting to Postgres."))
