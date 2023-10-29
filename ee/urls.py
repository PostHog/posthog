from typing import Any, List

from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls.conf import path
from rest_framework_extensions.routers import NestedRegistryItem

from ee.api import integration, time_to_see_data
from posthog.api.routing import DefaultRouterPlusPlus

from .api import (
    authentication,
    billing,
    dashboard_collaborator,
    debug_ch_queries,
    explicit_team_member,
    feature_flag_role_access,
    hooks,
    license,
    organization_resource_access,
    role,
    sentry_stats,
    subscription,
)
from .session_recordings import session_recording_playlist


def extend_api_router(
    root_router: DefaultRouterPlusPlus,
    *,
    projects_router: NestedRegistryItem,
    organizations_router: NestedRegistryItem,
    project_dashboards_router: NestedRegistryItem,
    project_feature_flags_router: NestedRegistryItem,
) -> None:
    root_router.register(r"billing-v2", billing.BillingViewset, "billing")
    root_router.register(r"license", license.LicenseViewSet)
    root_router.register(r"debug_ch_queries", debug_ch_queries.DebugCHQueries, "debug_ch_queries")
    root_router.register(r"time_to_see_data", time_to_see_data.TimeToSeeDataViewSet, "query_metrics")
    root_router.register(r"integrations", integration.PublicIntegrationViewSet)
    organization_roles_router = organizations_router.register(
        r"roles",
        role.RoleViewSet,
        "organization_roles",
        ["organization_id"],
    )
    organization_roles_router.register(
        r"role_memberships",
        role.RoleMembershipViewSet,
        "organization_role_memberships",
        ["organization_id", "role_id"],
    )
    project_feature_flags_router.register(
        r"role_access",
        feature_flag_role_access.FeatureFlagRoleAccessViewSet,
        "feature_flag_role_access",
        ["team_id", "feature_flag_id"],
    )
    organizations_router.register(
        r"resource_access",
        organization_resource_access.OrganizationResourceAccessViewSet,
        "organization_resource_access",
        ["organization_id"],
    )
    projects_router.register(r"hooks", hooks.HookViewSet, "project_hooks", ["team_id"])
    projects_router.register(
        r"explicit_members",
        explicit_team_member.ExplicitTeamMemberViewSet,
        "project_explicit_members",
        ["team_id"],
    )
    project_dashboards_router.register(
        r"collaborators",
        dashboard_collaborator.DashboardCollaboratorViewSet,
        "project_dashboard_collaborators",
        ["team_id", "dashboard_id"],
    )

    projects_router.register(r"subscriptions", subscription.SubscriptionViewSet, "subscriptions", ["team_id"])
    projects_router.register(
        r"session_recording_playlists",
        session_recording_playlist.SessionRecordingPlaylistViewSet,
        "project_session_recording_playlists",
        ["team_id"],
    )


# The admin interface is disabled on self-hosted instances, as its misuse can be unsafe
admin_urlpatterns = (
    [path("admin/", include("loginas.urls")), path("admin/", admin.site.urls)] if settings.ADMIN_PORTAL_ENABLED else []
)


urlpatterns: List[Any] = [
    path("api/saml/metadata/", authentication.saml_metadata_view),
    path("api/sentry_stats/", sentry_stats.sentry_stats),
    *admin_urlpatterns,
]
