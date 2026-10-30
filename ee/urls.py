from typing import Any

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.exceptions import NotRegistered
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from posthog.admin import register_all_admin
from posthog.admin.oauth2 import admin_oauth2_callback
from posthog.admin.oauth_views import admin_auth_check, admin_oauth_success
from posthog.api.sso import saml_metadata_view
from posthog.ingress.vercel.provider import build_vercel_provider
from posthog.ingress.views import build_webhook_view
from posthog.middleware import impersonated_session_logout
from posthog.views import api_key_search_view, redis_edit_ttl_view, redis_values_view

from products.cdp.backend.api import hooks

from ee.admin.loginas_views import loginas_user, upgrade_impersonation
from ee.api import integration
from ee.api.vercel import vercel_connect, vercel_sso

from .api import billing, conversation, core_memory, organization_billing, project_billing


def extend_api_router() -> None:
    from posthog.api import (
        organizations_router,
        projects_router,
        router as root_router,
    )

    from ee.api import max_tools

    root_router.register(r"billing", billing.BillingViewset, "billing")
    organizations_router.register(
        r"billing", organization_billing.OrganizationBillingViewSet, "organization_billing", ["organization_id"]
    )
    projects_router.register(r"billing", project_billing.ProjectBillingViewSet, "project_billing", ["team_id"])
    root_router.register(r"integrations", integration.PublicIntegrationViewSet)
    projects_router.register(r"hooks", hooks.HookViewSet, "project_hooks", ["team_id"])

    projects_router.register(r"conversations", conversation.ConversationViewSet, "project_conversations", ["team_id"])

    projects_router.register(r"core_memory", core_memory.MaxCoreMemoryViewSet, "project_core_memory", ["team_id"])

    projects_router.register(r"max_tools", max_tools.MaxToolsViewSet, "project_max_tools", ["team_id"])


# The admin interface is disabled on self-hosted instances, as its misuse can be unsafe
if settings.ADMIN_PORTAL_ENABLED:
    # `AdminSite.get_urls()` derives the `admin:app_list` URL pattern from the registry
    # when `admin.site.urls` below is read, and never rebuilds it. `LazyAdminRegistry`
    # fills the registry first, but `posthog/apps.py` skips it under `settings.TEST`.
    register_all_admin()

    # these models are auto-registered but we don't want to expose them to staff
    for model in (StaticDevice, TOTPDevice):
        try:
            admin.site.unregister(model)
        except NotRegistered:
            pass

    from posthog.admin.admins.distinct_id_usage_admin import distinct_id_usage_view
    from posthog.admin.admins.events_retention_admin import events_retention_view
    from posthog.admin.admins.health_check_admin import (
        health_check_list_view,
        health_check_runs_fragment_view,
        health_check_trigger_view,
    )
    from posthog.admin.admins.notebook_markdown_migration_admin import (
        notebook_markdown_migration_run_view,
        notebook_markdown_migration_stats_view,
        notebook_markdown_migration_view,
    )
    from posthog.admin.admins.resave_cohorts_admin import resave_cohorts_view
    from posthog.admin.admins.tophog_admin import tophog_dashboard_view, tophog_restrictions_view

    admin_urlpatterns = [
        # APPEND_SLASH is disabled globally, so redirect /admin to /admin/ explicitly
        path("admin", RedirectView.as_view(url="/admin/", permanent=False, query_string=True)),
        path("admin/oauth2/callback", admin_oauth2_callback, name="admin_oauth2_callback"),
        path("admin/oauth2/success", admin_oauth_success, name="admin_oauth_success"),
        path("admin/auth_check", admin_auth_check, name="admin_auth_check"),
        path("admin/redisvalues", redis_values_view, name="redis_values"),
        path("admin/redis/edit-ttl", redis_edit_ttl_view, name="redis_edit_ttl"),
        path("admin/apikeysearch", api_key_search_view, name="api_key_search"),
        path(
            "admin/resave-cohorts/",
            admin.site.admin_view(resave_cohorts_view),
            name="resave-cohorts",
        ),
        path(
            "admin/distinct-id-usage/",
            admin.site.admin_view(distinct_id_usage_view),
            name="distinct-id-usage",
        ),
        path(
            "admin/events-retention/",
            admin.site.admin_view(events_retention_view),
            name="events-retention",
        ),
        path(
            "admin/tophog/",
            admin.site.admin_view(tophog_dashboard_view),
            name="tophog-dashboard",
        ),
        path(
            "admin/tophog/restrictions/",
            admin.site.admin_view(tophog_restrictions_view),
            name="tophog-restrictions",
        ),
        path(
            "admin/health-checks/",
            admin.site.admin_view(health_check_list_view),
            name="health-checks",
        ),
        path(
            "admin/health-checks/<str:kind>/",
            admin.site.admin_view(health_check_trigger_view),
            name="health-check-trigger",
        ),
        path(
            "admin/health-checks/<str:kind>/runs/",
            admin.site.admin_view(health_check_runs_fragment_view),
            name="health-check-runs",
        ),
        path(
            "admin/notebook-markdown-migration/",
            admin.site.admin_view(notebook_markdown_migration_view),
            name="notebook-markdown-migration",
        ),
        path(
            "admin/notebook-markdown-migration/stats/",
            admin.site.admin_view(notebook_markdown_migration_stats_view),
            name="notebook-markdown-migration-stats",
        ),
        path(
            "admin/notebook-markdown-migration/run/",
            admin.site.admin_view(notebook_markdown_migration_run_view),
            name="notebook-markdown-migration-run",
        ),
        path(
            "admin/logout/",
            impersonated_session_logout,
            name="loginas-logout",
        ),
        path("admin/login/user/<str:user_id>/", loginas_user, name="loginas-user-login"),
        path("admin/impersonation/upgrade/", upgrade_impersonation, name="impersonation-upgrade"),
        # Temporary compatibility aliases for stable DuckgresServer admin URLs.
        path(
            "admin/posthog/duckgresserver/",
            RedirectView.as_view(url="/admin/managed_warehouse/duckgresserver/", permanent=False, query_string=True),
        ),
        path(
            "admin/posthog/duckgresserver/<path:url_suffix>",
            RedirectView.as_view(
                url="/admin/managed_warehouse/duckgresserver/%(url_suffix)s",
                permanent=False,
                query_string=True,
            ),
        ),
        path("admin/", include("loginas.urls")),
        path("admin/", admin.site.urls),
    ]
else:
    admin_urlpatterns = []


urlpatterns: list[Any] = [
    path("api/saml/metadata/", saml_metadata_view),
    re_path(r"^login/vercel/?$", vercel_sso.VercelSSOViewSet.as_view({"get": "sso_redirect"})),
    re_path(r"^login/vercel/continue/?$", vercel_sso.VercelSSOViewSet.as_view({"get": "sso_continue"})),
    re_path(
        r"^connect/vercel/callback/?$",
        vercel_connect.VercelConnectCallbackViewSet.as_view({"get": "callback"}),
    ),
    re_path(
        r"^api/vercel/connect/complete/?$",
        vercel_connect.VercelConnectLinkViewSet.as_view({"post": "complete"}),
    ),
    re_path(
        r"^api/vercel/connect/session/?$",
        vercel_connect.VercelConnectLinkViewSet.as_view({"get": "session_info"}),
    ),
    path("webhooks/vercel", build_webhook_view(build_vercel_provider()), name="vercel_webhooks"),
    # Stripe Projects provisioning (APP 0.1d)
    path("api/partners/stripe/", include("ee.partners.stripe.api.provisioning.urls")),
    # Agentic provisioning (partner account/resource provisioning + deep-link login)
    path("", include("ee.api.agentic_provisioning.urls")),
    *admin_urlpatterns,
]
