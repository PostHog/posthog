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
    from posthog.api import (
        project_dashboards_router,
        organizations_router,
        project_feature_flags_router,
        projects_router,
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

    projects_router.register(r"subscriptions", subscription.SubscriptionViewSet, "project_subscriptions", ["team_id"])
    projects_router.register(r"conversations", conversation.ConversationViewSet, "project_conversations", ["team_id"])
    projects_router.register(r"core_memory", core_memory.MaxCoreMemoryViewSet, "project_core_memory", ["team_id"])


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
