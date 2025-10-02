from typing import Any

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.sites import NotRegistered  # type: ignore[attr-defined]
from django.urls import include, re_path
from django.urls.conf import path
from django.views.decorators.csrf import csrf_exempt

from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from posthog.utils import opt_slash_path
from posthog.views import api_key_search_view, redis_values_view

from ee.admin.oauth_views import admin_auth_check, admin_oauth_success
from ee.api import integration
from ee.api.mcp.http import mcp_view
from ee.api.vercel import vercel_sso
from ee.middleware import admin_oauth2_callback
from ee.support_sidebar_max.views import MaxChatViewSet

from .api import (
    authentication,
    billing,
    conversation,
    core_memory,
    dashboard_collaborator,
    hooks,
    license,
    sentry_stats,
    subscription,
)
from .api.rbac import role


def extend_api_router() -> None:
    from posthog.api import (
        environment_dashboards_router,
        environments_router,
        legacy_project_dashboards_router,
        organizations_router,
        register_grandfathered_environment_nested_viewset,
        router as root_router,
    )

    from ee.api import max_tools, session_summaries

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
    register_grandfathered_environment_nested_viewset(r"hooks", hooks.HookViewSet, "environment_hooks", ["team_id"])

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

    environments_router.register(
        r"session_summaries", session_summaries.SessionSummariesViewSet, "environment_session_summaries", ["team_id"]
    )


# The admin interface is disabled on self-hosted instances, as its misuse can be unsafe
if settings.ADMIN_PORTAL_ENABLED:
    # these models are auto-registered but we don't want to expose them to staff
    for model in (StaticDevice, TOTPDevice):
        try:
            admin.site.unregister(model)
        except NotRegistered:
            pass

    admin_urlpatterns = [
        re_path(r"^admin/oauth2/callback$", admin_oauth2_callback, name="admin_oauth2_callback"),
        re_path(r"^admin/oauth2/success$", admin_oauth_success, name="admin_oauth_success"),
        re_path(r"^admin/auth_check$", admin_auth_check, name="admin_auth_check"),
        re_path(r"^admin/redisvalues$", redis_values_view, name="redis_values"),
        re_path(r"^admin/apikeysearch$", api_key_search_view, name="api_key_search"),
        path("admin/", include("loginas.urls")),
        path("admin/", admin.site.urls),
    ]
else:
    admin_urlpatterns = []


urlpatterns: list[Any] = [
    path("api/saml/metadata/", authentication.saml_metadata_view),
    path("api/sentry_stats/", sentry_stats.sentry_stats),
    path("max/chat/", csrf_exempt(MaxChatViewSet.as_view({"post": "create"})), name="max_chat"),
    path("login/vercel/", vercel_sso.VercelSSOViewSet.as_view({"get": "sso_redirect"})),
    path("login/vercel/continue", vercel_sso.VercelSSOViewSet.as_view({"get": "sso_continue"})),
    opt_slash_path("mcp", csrf_exempt(mcp_view)),
    *admin_urlpatterns,
]
