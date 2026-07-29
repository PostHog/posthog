"""Routes for the agentic provisioning namespace, included from ``ee/urls.py``.

Partner endpoints live under ``/api/agentic/`` and are ``csrf_exempt`` (they
authenticate with a signed client assertion, client credentials, PKCE, or an OAuth
access token, never a session cookie). The consent and login routes are
browser-facing and keep CSRF protection.
"""

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from ee.api.agentic_provisioning import views

urlpatterns = [
    path(
        "api/agentic/provisioning/client_registration",
        csrf_exempt(views.ClientRegistrationView.as_view()),
        name="agentic_provisioning_client_registration",
    ),
    path(
        "api/agentic/provisioning/account_requests",
        csrf_exempt(views.AccountRequestsView.as_view()),
        name="agentic_provisioning_account_requests",
    ),
    path(
        "api/agentic/oauth/token",
        csrf_exempt(views.OAuthTokenView.as_view()),
        name="agentic_provisioning_oauth_token",
    ),
    path(
        "api/agentic/provisioning/resources",
        csrf_exempt(views.ResourcesCreateView.as_view()),
        name="agentic_provisioning_resources_create",
    ),
    path(
        "api/agentic/provisioning/resources/<str:resource_id>/rotate_credentials",
        csrf_exempt(views.RotateCredentialsView.as_view()),
        name="agentic_provisioning_rotate_credentials",
    ),
    path(
        "api/agentic/provisioning/resources/<str:resource_id>/remove",
        csrf_exempt(views.ResourceRemoveView.as_view()),
        name="agentic_provisioning_resource_remove",
    ),
    path(
        "api/agentic/provisioning/resources/<str:resource_id>/github_integration",
        csrf_exempt(views.GitHubIntegrationView.as_view()),
        name="agentic_provisioning_github_integration",
    ),
    path(
        "api/agentic/provisioning/resources/<str:resource_id>/wizard_runs",
        csrf_exempt(views.WizardRunsView.as_view()),
        name="agentic_provisioning_wizard_runs",
    ),
    path(
        "api/agentic/provisioning/resources/<str:resource_id>",
        csrf_exempt(views.ResourceDetailView.as_view()),
        name="agentic_provisioning_resource_detail",
    ),
    path(
        "api/agentic/provisioning/deep_links",
        csrf_exempt(views.DeepLinksView.as_view()),
        name="agentic_provisioning_deep_links",
    ),
    path(
        "api/agentic/provisioning/github/grants",
        csrf_exempt(views.GitHubGrantsCreateView.as_view()),
        name="agentic_provisioning_github_grants_create",
    ),
    path(
        "api/agentic/provisioning/github/grants/<str:grant_id>/repositories",
        csrf_exempt(views.GitHubGrantRepositoriesView.as_view()),
        name="agentic_provisioning_github_grant_repositories",
    ),
    path("api/agentic/authorize", views.agentic_authorize, name="agentic_authorize"),
    path("api/agentic/authorize/pending/", views.AuthorizePendingView.as_view(), name="agentic_authorize_pending"),
    path("api/agentic/authorize/confirm/", views.AuthorizeConfirmView.as_view(), name="agentic_authorize_confirm"),
    path("agentic/login", views.agentic_login, name="agentic_login"),
]
