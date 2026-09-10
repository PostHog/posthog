"""Routes for the Stripe Projects provisioning namespace.

Included from ``ee/urls.py`` under ``api/partners/stripe/``. Stripe builds
provider URLs as ``provisioning.base_url + "provisioning/<name>"`` (the token
endpoint is configured explicitly in the app manifest), so the concrete paths
are ``/api/partners/stripe/provisioning/...`` and
``/api/partners/stripe/oauth/token``.
"""

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from ee.partners.stripe.api.provisioning import views
from ee.partners.stripe.api.provisioning.login import stripe_provisioning_login

urlpatterns = [
    path(
        "login",
        stripe_provisioning_login,
        name="stripe_provisioning_login",
    ),
    path(
        "provisioning/health",
        csrf_exempt(views.HealthView.as_view()),
        name="stripe_provisioning_health",
    ),
    path(
        "provisioning/services",
        csrf_exempt(views.ServicesView.as_view()),
        name="stripe_provisioning_services",
    ),
    path(
        "provisioning/account_requests",
        csrf_exempt(views.AccountRequestsView.as_view()),
        name="stripe_provisioning_account_requests",
    ),
    path(
        "oauth/token",
        csrf_exempt(views.OAuthTokenView.as_view()),
        name="stripe_provisioning_oauth_token",
    ),
    path(
        "provisioning/resources",
        csrf_exempt(views.ResourcesCreateView.as_view()),
        name="stripe_provisioning_resources_create",
    ),
    path(
        "provisioning/resources/<str:resource_id>/rotate_credentials",
        csrf_exempt(views.RotateCredentialsView.as_view()),
        name="stripe_provisioning_rotate_credentials",
    ),
    path(
        "provisioning/resources/<str:resource_id>/update_service",
        csrf_exempt(views.UpdateServiceView.as_view()),
        name="stripe_provisioning_update_service",
    ),
    path(
        "provisioning/resources/<str:resource_id>/remove",
        csrf_exempt(views.ResourceRemoveView.as_view()),
        name="stripe_provisioning_resource_remove",
    ),
    path(
        "provisioning/resources/<str:resource_id>",
        csrf_exempt(views.ResourceDetailView.as_view()),
        name="stripe_provisioning_resource_detail",
    ),
    path(
        "provisioning/deep_links",
        csrf_exempt(views.DeepLinksView.as_view()),
        name="stripe_provisioning_deep_links",
    ),
]
