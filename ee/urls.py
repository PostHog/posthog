from typing import Any

from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls.conf import path

from ee.api import integration
from .api.rbac import organization_resource_access, role

from .api import (
    authentication,
    billing,
    dashboard_collaborator,
    explicit_team_member,
    feature_flag_role_access,
    hooks,
    license,
    sentry_stats,
    subscription,
)
from .session_recordings import session_recording_playlist


def extend_api_router() -> None:
    from posthog.api import (
        router as root_router,
        register_grandfathered_environment_nested_viewset,
        projects_router,
        organizations_router,
        project_feature_flags_router,
        project_dashboards_router,
    )

    root_router.register(r"billing", billing.BillingViewset, "billing")
    root_router.register(r"license", license.LicenseViewSet)
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

    # ROUTES TO BE DEPRECATED
    project_feature_flags_router.register(
        r"role_access",
        feature_flag_role_access.FeatureFlagRoleAccessViewSet,
        "project_feature_flag_role_access",
        ["project_id", "feature_flag_id"],
    )
    organizations_router.register(
        r"resource_access",
        organization_resource_access.OrganizationResourceAccessViewSet,
        "organization_resource_access",
        ["organization_id"],
    )
    register_grandfathered_environment_nested_viewset(r"hooks", hooks.HookViewSet, "environment_hooks", ["team_id"])
    register_grandfathered_environment_nested_viewset(
        r"explicit_members",
        explicit_team_member.ExplicitTeamMemberViewSet,
        "environment_explicit_members",
        ["team_id"],
    )
    project_dashboards_router.register(
        r"collaborators",
        dashboard_collaborator.DashboardCollaboratorViewSet,
        "project_dashboard_collaborators",
        ["project_id", "dashboard_id"],
    )

    register_grandfathered_environment_nested_viewset(
        r"subscriptions", subscription.SubscriptionViewSet, "environment_subscriptions", ["team_id"]
    )
    projects_router.register(
        r"session_recording_playlists",
        session_recording_playlist.SessionRecordingPlaylistViewSet,
        "project_session_recording_playlists",
        ["project_id"],
    )


# The admin interface is disabled on self-hosted instances, as its misuse can be unsafe
admin_urlpatterns = (
    [path("admin/", include("loginas.urls")), path("admin/", admin.site.urls)] if settings.ADMIN_PORTAL_ENABLED else []
)


urlpatterns: list[Any] = [
    path("api/saml/metadata/", authentication.saml_metadata_view),
    path("api/sentry_stats/", sentry_stats.sentry_stats),
    *admin_urlpatterns,
]
