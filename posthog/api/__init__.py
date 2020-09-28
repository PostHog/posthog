import posthoganalytics
from django.conf import settings
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
router.register(r"element", element.ElementViewSet)
router.register(r"feature_flag", feature_flag.FeatureFlagViewSet)
router.register(r"funnel", funnel.FunnelViewSet)
router.register(r"dashboard", dashboard.DashboardsViewSet)
router.register(r"dashboard_item", dashboard.DashboardItemsViewSet)
router.register(r"cohort", cohort.CohortViewSet)
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, basename="personal_api_keys")
router.register(r"team/user", team_user.TeamUserViewSet)

if check_ee_enabled():
    try:
        from ee.clickhouse.views import (
            ClickhouseActions,
            ClickhouseEvents,
            ClickhouseInsights,
            ClickhousePathsViewSet,
            ClickhousePerson,
        )

        if posthoganalytics.feature_enabled("ch-action") or settings.DEBUG:
            router.register(r"action", ClickhouseActions, basename="action")
        else:
            router.register(r"action", action.ActionViewSet)

        if posthoganalytics.feature_enabled("ch-event") or settings.DEBUG:
            router.register(r"event", ClickhouseEvents, basename="event")
        else:
            router.register(r"event", event.EventViewSet)

        if posthoganalytics.feature_enabled("ch-insight") or settings.DEBUG:
            router.register(r"insight", ClickhouseInsights, basename="insight")
        else:
            router.register(r"insight", insight.InsightViewSet)

        if posthoganalytics.feature_enabled("ch-person") or settings.DEBUG:
            router.register(r"person", ClickhousePerson, basename="person")
        else:
            router.register(r"person", person.PersonViewSet)

        if posthoganalytics.feature_enabled("ch-person") or settings.DEBUG:
            router.register(r"paths", ClickhousePathsViewSet, basename="paths")
        else:
            router.register(r"paths", paths.PathsViewSet, basename="paths")

    except ImportError:
        print("Clickhouse enabled but missing enterprise capabilities. Defaulting to postgres")
else:
    router.register(r"insight", insight.InsightViewSet)
    router.register(r"action", action.ActionViewSet)
    router.register(r"person", person.PersonViewSet)
    router.register(r"event", event.EventViewSet)
    router.register(r"paths", paths.PathsViewSet, basename="paths")
