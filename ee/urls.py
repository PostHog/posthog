from typing import Any

from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls.conf import path
from django.views.decorators.csrf import csrf_exempt

from ee.api import integration
from ee.support_sidebar_max.views import MaxChatViewSet

from .api import (
    authentication,
    billing,
    conversation,
    core_memory,
    dashboard_collaborator,
    explicit_team_member,
    feature_flag_role_access,
    hooks,
    license,
    sentry_stats,
    subscription,
)
from .api.rbac import organization_resource_access, role


def extend_api_router() -> None:
    from ee.api import max_tools
    from posthog.api import (
        environment_dashboards_router,
        environments_router,
        legacy_project_dashboards_router,
        organizations_router,
        project_feature_flags_router,
        register_grandfathered_environment_nested_viewset,
        router as root_router,
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
    # Start: routes to be deprecated
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
    # End: routes to be deprecated
    register_grandfathered_environment_nested_viewset(r"hooks", hooks.HookViewSet, "environment_hooks", ["team_id"])
    register_grandfathered_environment_nested_viewset(
        r"explicit_members",
        explicit_team_member.ExplicitTeamMemberViewSet,
        "environment_explicit_members",
        ["team_id"],
    )

    environment_dashboards_router.register(
        r"collaborators",
        dashboard_collaborator.DashboardCollaboratorViewSet,
        "environment_dashboard_collaborators",
        ["project_id", "dashboard_id"],
    )
    legacy_project_dashboards_router.register(
        r"collaborators",
        dashboard_collaborator.DashboardCollaboratorViewSet,
        "project_dashboard_collaborators",
        ["project_id", "dashboard_id"],
    )

    register_grandfathered_environment_nested_viewset(
        r"subscriptions", subscription.SubscriptionViewSet, "environment_subscriptions", ["team_id"]
    )

    environments_router.register(
        r"conversations", conversation.ConversationViewSet, "environment_conversations", ["team_id"]
    )

    environments_router.register(
        r"core_memory", core_memory.MaxCoreMemoryViewSet, "environment_core_memory", ["team_id"]
    )

    environments_router.register(r"max_tools", max_tools.MaxToolsViewSet, "environment_max_tools", ["team_id"])


# The admin interface is disabled on self-hosted instances, as its misuse can be unsafe
admin_urlpatterns = (
    [path("admin/", include("loginas.urls")), path("admin/", admin.site.urls)] if settings.ADMIN_PORTAL_ENABLED else []
)


urlpatterns: list[Any] = [
    path("api/saml/metadata/", authentication.saml_metadata_view),
    path("api/sentry_stats/", sentry_stats.sentry_stats),
    path("max/chat/", csrf_exempt(MaxChatViewSet.as_view({"post": "create"})), name="max_chat"),
    *admin_urlpatterns,
]
