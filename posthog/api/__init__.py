from rest_framework import decorators, exceptions

from posthog.api.utils import DefaultRouterPlusPlus
from posthog.ee import is_ee_enabled

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
    organization,
    organization_invite,
    organization_member,
    paths,
    person,
    personal_api_key,
    plugin,
    team,
)


@decorators.api_view(["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@decorators.authentication_classes([])
@decorators.permission_classes([])
def api_not_found(request):
    raise exceptions.NotFound(detail="Endpoint not found.")


router = DefaultRouterPlusPlus()
# legacy endpoints (to be removed eventually)
router.register(r"annotation", annotation.LegacyAnnotationsViewSet)
router.register(r"feature_flag", feature_flag.LegacyFeatureFlagViewSet)
router.register(r"funnel", funnel.LegacyFunnelViewSet)
router.register(r"dashboard", dashboard.LegacyDashboardsViewSet)
router.register(r"dashboard_item", dashboard.LegacyDashboardItemsViewSet)
router.register(r"cohort", cohort.LegacyCohortViewSet)
router.register(r"personal_api_keys", personal_api_key.PersonalAPIKeyViewSet, "personal_api_keys")
router.register(r"plugin", plugin.PluginViewSet)
router.register(r"plugin_config", plugin.PluginConfigViewSet)
organizations_router = router.register(r"organizations", organization.OrganizationViewSet)
organizations_router.register(
    r"members", organization_member.OrganizationMemberViewSet, "organization_members", ["organization_id"],
)
organizations_router.register(
    r"invites", organization_invite.OrganizationInviteViewSet, "organization_invites", ["organization_id"],
)

if is_ee_enabled():
    try:
        from ee.clickhouse.views.actions import ClickhouseActionsViewSet, LegacyClickhouseActionsViewSet
        from ee.clickhouse.views.element import ClickhouseElementViewSet, LegacyClickhouseElementViewSet
        from ee.clickhouse.views.events import ClickhouseEventsViewSet, LegacyClickhouseEventsViewSet
        from ee.clickhouse.views.insights import ClickhouseInsightsViewSet, LegacyClickhouseInsightsViewSet
        from ee.clickhouse.views.paths import ClickhousePathsViewSet, LegacyClickhousePathsViewSet
        from ee.clickhouse.views.person import ClickhousePersonViewSet, LegacyClickhousePersonViewSet
    except ImportError as e:
        print("ClickHouse enabled but missing enterprise capabilities. Defaulting to Postgres.")
        print(e)
    else:
        # legacy endpoints (to be removed eventually)
        router.register(r"action", LegacyClickhouseActionsViewSet, basename="action")
        router.register(r"event", LegacyClickhouseEventsViewSet, basename="event")
        router.register(r"insight", LegacyClickhouseInsightsViewSet, basename="insight")
        router.register(r"person", LegacyClickhousePersonViewSet, basename="person")
        router.register(r"paths", LegacyClickhousePathsViewSet, basename="paths")
        router.register(r"element", LegacyClickhouseElementViewSet, basename="element")
else:
    # legacy endpoints (to be removed eventually)
    router.register(r"insight", insight.LegacyInsightViewSet)
    router.register(r"action", action.LegacyActionViewSet)
    router.register(r"person", person.LegacyPersonViewSet)
    router.register(r"event", event.LegacyEventViewSet)
    router.register(r"paths", paths.LegacyPathsViewSet, basename="paths")
    router.register(r"element", element.LegacyElementViewSet)
