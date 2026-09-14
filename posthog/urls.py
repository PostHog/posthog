from django.conf import settings
from django.urls import include, path, re_path
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import RedirectView

from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from two_factor.urls import urlpatterns as tf_urls

from posthog.api import (
    api_not_found,
    authentication,
    github,
    leaked_key,
    playwright_setup,
    report,
    router,
    sharing,
    signup,
    site_app,
    two_factor_reset,
    unsubscribe,
    uploaded_media,
    user,
)
from posthog.api.github_callback.views import github_oauth_callback, github_setup_callback
from posthog.api.github_webhooks.views import github_webhook
from posthog.api.integration_connect import integration_connect_redirect
from posthog.api.oauth.connected_apps import ConnectedAppsViewSet
from posthog.api.oauth.hogli_metadata import HOGLI_METADATA_PATH, HogliClientMetadataView
from posthog.api.oauth.raycast_metadata import RAYCAST_METADATA_PATH, RaycastClientMetadataView
from posthog.api.oauth.toolbar_views import authorize_and_redirect
from posthog.api.oauth.wizard_metadata import WIZARD_METADATA_PATH, WizardClientMetadataView
from posthog.api.sdk_health import sdk_health
from posthog.api.two_factor_qrcode import CacheAwareQRGeneratorView
from posthog.api.web_experiment import web_experiments
from posthog.ee_urls import ee_urlpatterns
from posthog.frontend_views import home, home_with_region_redirect
from posthog.oauth2_urls import urlpatterns as oauth2_urls
from posthog.temporal.codec_server import decode_payloads
from posthog.web_bot_auth import http_message_signatures_directory

from products.ai_observability.backend.api.personal_spend import PersonalSpendEUProxyViewSet
from products.canvas.backend.artifacts import canvas_artifact
from products.cdp.backend.api import hog_function_template
from products.conversations.backend.api.internal import InternalTicketView as ConversationsInternalTicketView
from products.customer_analytics.backend.presentation.views.internal import (
    InternalAccountCustomPropertiesView as CustomerAnalyticsInternalAccountCustomPropertiesView,
    InternalAccountView as CustomerAnalyticsInternalAccountView,
)
from products.demo.backend.facade.api import demo_route
from products.early_access_features.backend.api import early_access_features
from products.legal_documents.backend.presentation.webhook import legal_document_pandadoc_webhook
from products.messaging.backend.api.customerio_webhook import CustomerIOWebhookView
from products.messaging.backend.api.push_subscriptions import push_subscriptions
from products.notebooks.backend.facade.sql_v2 import (
    notebook_sql_v2_callback,
    notebook_sql_v2_data_plane,
    notebook_sql_v2_data_plane_status,
)
from products.product_tours.backend.api import product_tours
from products.signals.backend import views as signals_views
from products.signals.backend.views import SignalUserAutonomyConfigView as signals_user_autonomy_view
from products.slack_app.backend.api import (
    posthog_code_event_handler,
    posthog_code_interactivity_handler,
    slack_workspace_claims_view,
)
from products.slack_app.backend.views import (
    slack_app_command_handler,
    slack_user_link_authorize,
    slack_user_link_callback,
)
from products.stamphog.backend.facade.webhooks import stamphog_github_webhook
from products.streamlit_apps.backend.presentation.bridge_views import StreamlitBridgeView
from products.surveys.backend.api.survey import public_survey_page
from products.tasks.backend.facade.agent_proxy import agent_proxy_callback
from products.user_interviews.backend.presentation.webhooks import (
    start_call as user_interviews_start_call,
    vapi_webhook,
)
from products.warehouse_sources.backend.presentation.views.public_source_configs import PublicSourceConfigViewSet
from products.workflows.backend.api import hog_flow, hog_flow_template
from products.workflows.backend.api.ses_events_webhook import ses_tenant_events_webhook

from .utils import opt_slash_path
from .views import (
    handler500 as handler500,
    health,
    login_required,
    metrics_view,
    preferences_page,
    preflight_check,
    render_query,
    replay_player_frame,
    robots_txt,
    security_txt,
    stats,
    update_preferences,
)

urlpatterns = [
    # EU spend must precede both the API router and the API fallback.
    *(
        [
            path(
                "api/llm_analytics/@me/spend/",
                PersonalSpendEUProxyViewSet.as_view({"get": "list"}),
                name="personal_spend_eu",
            )
        ]
        if settings.CLOUD_DEPLOYMENT == "EU"
        else []
    ),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Optional UI:
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    # Health check probe endpoints for K8s
    # NOTE: We have _health, livez, and _readyz. _health is deprecated and
    # is only included for compatability with old installations. For new
    # operations livez and readyz should be used.
    # Same-origin shell the session replay player mounts rrweb into. Unauthenticated because
    # shared recordings render the player too; it carries no data of its own. The path ends in
    # index.html so Storybook's static server, which does no directory-index resolution, serves the
    # same file at the same URL.
    path("replay_player_frame/index.html", replay_player_frame),
    opt_slash_path("_health", health),
    opt_slash_path("_stats", stats),
    opt_slash_path("_preflight", preflight_check),
    # ee
    *ee_urlpatterns,
    # api
    path("api/unsubscribe", unsubscribe.unsubscribe),
    path("api/alerts/github", github.SecretAlert.as_view()),
    opt_slash_path("api/revoke_leaked_key", leaked_key.PublicLeakedKeyReport.as_view()),
    path(
        "api/legal_documents/pandadoc",
        csrf_exempt(legal_document_pandadoc_webhook),
        name="legal_document_pandadoc_webhook",
    ),
    path(
        "api/users/<str:user_id>/signal_autonomy/",
        signals_user_autonomy_view.as_view(),
        name="user_signal_autonomy",
    ),
    path("api/projects/<int:team_id>/messaging/customerio/webhook/", csrf_exempt(CustomerIOWebhookView.as_view())),
    path(
        "api/user_interviews/vapi_webhook/",
        csrf_exempt(vapi_webhook),
        name="user_interviews_vapi_webhook",
    ),
    path(
        "api/user_interviews/share/<str:access_token>/start_call/",
        csrf_exempt(user_interviews_start_call),
        name="user_interviews_start_call",
    ),
    path("api/sdk_health/", sdk_health),
    path("api/conversations/", include("products.conversations.backend.api.urls")),
    path("api/customer_analytics/", include("products.customer_analytics.backend.presentation.views.urls")),
    path(
        "api/projects/<int:parent_lookup_team_id>/mcp_analytics/",
        include("products.mcp_analytics.backend.presentation.urls"),
    ),
    path(
        "api/projects/<int:parent_lookup_team_id>/property_access_controls/",
        include("products.access_control.backend.presentation.urls"),
    ),
    path(
        "api/streamlit_bridge/query/",
        csrf_exempt(StreamlitBridgeView.as_view()),
        name="streamlit_bridge_query",
    ),
    path("api/", include(router.urls)),
    # Override the tf_urls QRGeneratorView to use the cache-aware version (handles session race conditions)
    path("account/two_factor/qrcode/", CacheAwareQRGeneratorView.as_view()),
    path("", include(tf_urls)),
    opt_slash_path("api/user/prepare_toolbar_preloaded_flags", user.prepare_toolbar_preloaded_flags),
    opt_slash_path("api/user/get_toolbar_preloaded_flags", user.get_toolbar_preloaded_flags),
    opt_slash_path("api/user/toolbar_oauth_refresh", user.toolbar_oauth_refresh),
    path("toolbar_oauth/authorize/", login_required(user.toolbar_oauth_authorize)),
    path("toolbar_oauth/callback", user.toolbar_oauth_callback),
    path("toolbar_oauth/check", user.toolbar_oauth_check),
    opt_slash_path("api/user/redirect_to_site", user.redirect_to_site),
    opt_slash_path("api/user/redirect_to_website", user.redirect_to_website),
    opt_slash_path("api/early_access_features", early_access_features),
    opt_slash_path("api/web_experiments", web_experiments),
    opt_slash_path("api/push_subscriptions", push_subscriptions),
    opt_slash_path("api/product_tours", product_tours),
    re_path(r"^external_surveys/(?P<survey_id>[^/]+)/?$", public_survey_page),
    opt_slash_path("api/signup/precheck", signup.SignupEmailPrecheckViewset.as_view()),
    opt_slash_path("api/signup/resend-invite", signup.SignupResendInviteViewset.as_view()),
    opt_slash_path("api/signup", signup.SignupViewset.as_view()),
    opt_slash_path("api/social_signup", signup.SocialSignupViewset.as_view()),
    path("api/signup/<str:invite_id>/", signup.InviteSignupViewset.as_view()),
    path(
        "api/reset/<str:user_uuid>/",
        authentication.PasswordResetCompleteViewSet.as_view({"get": "retrieve", "post": "create"}),
    ),
    path(
        "api/reset_2fa/<str:user_uuid>/",
        two_factor_reset.TwoFactorResetViewSet.as_view({"get": "retrieve", "post": "create"}),
    ),
    opt_slash_path(
        "api/public_hog_function_templates",
        hog_function_template.PublicHogFunctionTemplateViewSet.as_view({"get": "list"}),
    ),
    opt_slash_path(
        "api/public_hog_flow_templates",
        hog_flow_template.PublicHogFlowTemplateViewSet.as_view({"get": "list"}),
    ),
    opt_slash_path(
        "api/public_source_configs",
        PublicSourceConfigViewSet.as_view({"get": "list"}),
    ),
    # Internal agent-proxy side-effect callback (auth: sandbox event ingest JWT)
    path(
        "internal/tasks/runs/<str:run_id>/agent-proxy-callback/",
        csrf_exempt(agent_proxy_callback),
    ),
    # Internal SQLV2 run result callback (auth: signed callback token)
    path(
        "internal/notebooks/runs/<str:run_id>/result/",
        csrf_exempt(notebook_sql_v2_callback),
    ),
    # Internal SQLV2 data plane — the sandbox's HogQL read path (auth: signed data-plane token)
    path(
        "internal/notebooks/data_plane/query/",
        csrf_exempt(notebook_sql_v2_data_plane),
    ),
    path(
        "internal/notebooks/data_plane/query/<str:query_id>/",
        csrf_exempt(notebook_sql_v2_data_plane_status),
    ),
    # Internal service-to-service endpoints (authenticated with POSTHOG_INTERNAL_SERVICE_TOKEN)
    path(
        "api/projects/<str:team_id>/internal/hog_flows/user_blast_radius",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"post": "internal_user_blast_radius"})),
    ),
    path(
        "api/projects/<str:team_id>/internal/hog_flows/user_blast_radius_persons",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"post": "internal_user_blast_radius_persons"})),
    ),
    path(
        "api/projects/<str:team_id>/internal/hog_flows/account_audience",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"post": "internal_account_audience"})),
    ),
    path(
        "api/internal/hog_flows/process_due_schedules",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"post": "internal_process_due_schedules"})),
    ),
    path(
        "api/projects/<str:team_id>/internal/hog_flows/batch_jobs/<str:batch_job_id>/status",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"put": "internal_update_batch_job_status"})),
    ),
    path(
        "api/projects/<str:team_id>/internal/signals/emit",
        csrf_exempt(signals_views.InternalSignalViewSet.as_view({"post": "emit"})),
    ),
    # Ticket route for the CDP worker's workflow actions (auth: scoped service JWT)
    path(
        "api/projects/<str:team_id>/internal/conversations/tickets/<uuid:ticket_id>",
        csrf_exempt(ConversationsInternalTicketView.as_view()),
    ),
    # Account routes for the CDP worker's workflow actions (auth: scoped service JWT)
    path(
        "api/projects/<str:team_id>/internal/customer_analytics/account",
        csrf_exempt(CustomerAnalyticsInternalAccountView.as_view()),
    ),
    path(
        "api/projects/<str:team_id>/internal/customer_analytics/account/custom_property_values",
        csrf_exempt(CustomerAnalyticsInternalAccountCustomPropertiesView.as_view()),
    ),
    # Test setup endpoint (only available in TEST mode)
    path("api/setup_test/<str:test_name>/", csrf_exempt(playwright_setup.setup_test)),
    opt_slash_path(
        "api/oauth/connected-apps",
        ConnectedAppsViewSet.as_view({"get": "list"}),
    ),
    path(
        "api/oauth/connected-apps/<uuid:pk>/revoke/",
        ConnectedAppsViewSet.as_view({"post": "revoke"}),
    ),
    path(
        WIZARD_METADATA_PATH,
        WizardClientMetadataView.as_view(),
        name="wizard-client-metadata",
    ),
    path(
        RAYCAST_METADATA_PATH,
        RaycastClientMetadataView.as_view(),
        name="raycast-client-metadata",
    ),
    path(
        HOGLI_METADATA_PATH,
        HogliClientMetadataView.as_view(),
        name="hogli-client-metadata",
    ),
    re_path(r"^api.+", api_not_found),
    path("authorize_and_redirect/", login_required(authorize_and_redirect)),
    path("integrations/connect/<str:kind>/", login_required(integration_connect_redirect)),
    path(
        "shared_dashboard/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path(
        "shared/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path(
        "embedded/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path(
        "interview/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path("render_query", render_query, name="render_query"),
    path("exporter", sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"})),
    path(
        "exporter/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path("site_app/<int:id>/<str:token>/<str:hash>/", site_app.get_site_app),
    re_path(r"^demo.*", login_required(demo_route)),
    path("", include((oauth2_urls, "oauth2_provider"), namespace="oauth2_provider")),
    # ingestion
    # NOTE: When adding paths here that should be public make sure to update ALWAYS_ALLOWED_ENDPOINTS in middleware.py
    opt_slash_path("report", report.get_csp_event),  # CSP violation reports
    opt_slash_path("robots.txt", robots_txt),
    opt_slash_path(".well-known/security.txt", security_txt),
    opt_slash_path(".well-known/http-message-signatures-directory", http_message_signatures_directory),
    # auth
    opt_slash_path("logout", authentication.logout, name="logout"),
    path(
        "login/<str:backend>/", authentication.sso_login, name="social_begin"
    ),  # overrides from `social_django.urls` to validate proper license
    # GitHub account linking (identity-only, separate from the login pipeline).
    # Must precede `social_django.urls` so the latter's `complete/<str:backend>/` doesn't swallow it.
    path("complete/github-link/", github_oauth_callback, name="github_link_complete"),
    opt_slash_path(
        "integrations/github/callback", github_setup_callback, name="github_team_integration_setup_callback"
    ),
    # Slack user-identity linking — mirrors the GitHub per-user pattern above,
    # and likewise must precede `social_django.urls` for the same reason.
    path("complete/slack-link/start/", slack_user_link_authorize, name="slack_link_start"),
    path("complete/slack-link/", slack_user_link_callback, name="slack_link_complete"),
    path("", include("social_django.urls", namespace="social")),
    path("uploaded_media/<str:image_uuid>", uploaded_media.download),
    opt_slash_path("slack/interactivity-callback", posthog_code_interactivity_handler),
    opt_slash_path("slack/event-callback", posthog_code_event_handler),
    opt_slash_path("slack/command-callback", slack_app_command_handler),
    opt_slash_path("slack/workspace/claims", slack_workspace_claims_view),
    # GitHub App webhook — fans out to tasks (PRs) and conversations (issues)
    opt_slash_path("webhooks/github/pr", github_webhook),
    opt_slash_path("webhooks/github", github_webhook),
    # Stamphog runs as its own GitHub App with a dedicated inbound endpoint (not the fan-out above)
    opt_slash_path("webhooks/stamphog/github", stamphog_github_webhook),
    # AWS SES tenant reputation events (EventBridge -> SNS HTTPS subscription)
    opt_slash_path("webhooks/workflows/ses-events", ses_tenant_events_webhook),
    # Message preferences
    path("messaging-preferences/<str:token>/", preferences_page, name="message_preferences"),
    opt_slash_path("messaging-preferences/update", update_preferences, name="message_preferences_update"),
    # In production metrics use a separate port (8001), so external clients cannot
    # see them. See bin/granian_metrics.py for the production metrics setup.
    *(
        [path("_metrics", metrics_view), path("decode", decode_payloads, name="temporal_decode")]
        if settings.DEBUG
        else []
    ),
    # Used in posthog-js e2e tests.
    *([path("delete_events/", playwright_setup.delete_events)] if settings.TEST else []),
    # Temporal UI decryption is needed in tests even when DEBUG is off.
    *([path("decode", decode_payloads, name="temporal_decode")] if settings.TEST and not settings.DEBUG else []),
    re_path(r"^canvas-artifacts/(?P<token>[^/]+)/(?P<artifact_path>.+)$", canvas_artifact, name="canvas-artifact"),
    # Preserve the host and query when redirecting the legacy signup URL.
    opt_slash_path("sign-up", RedirectView.as_view(url="/signup", permanent=True, query_string=True)),
    # Public frontend routes must precede the authenticated catch-all.
    re_path("preflight", home),
    re_path("signup", home),
    re_path(r"signup\/[A-Za-z0-9\-]*", home),
    re_path("reset", home),
    re_path("organization/billing/subscribed", home),
    re_path("organization/confirm-creation", home),
    re_path("login", home),
    re_path("unsubscribe", home),
    # Public bridges for desktop-app share links — deep-link into PostHog Desktop.
    re_path(r"code/canvas/[^/]+/[^/]+", home),
    re_path(r"code/task/[^/]+", home),
    re_path("verify_email", home),
    re_path(r"agentic/account-mismatch", home),
    # OAuth redirect target when logging the local frontend into a remote cloud region;
    # the SPA handles the code→token exchange client-side, so it must load without auth.
    re_path(r"^oauth/callback", home),
    re_path(r"^.*", home_with_region_redirect),
]
