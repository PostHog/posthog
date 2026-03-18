from django.conf import settings
from django.utils import timezone

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.models.oauth import find_oauth_access_token

BEARER_PREFIX = "Bearer "


class StripeProvisioningBearerAuthentication(BaseAuthentication):
    def authenticate(self, request: Request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(BEARER_PREFIX):
            return None

        token_value = auth_header[len(BEARER_PREFIX) :].strip()
        if not token_value:
            return None

        access_token = find_oauth_access_token(token_value)
        if access_token is None:
            raise AuthenticationFailed("Invalid access token")

        if access_token.expires and access_token.expires < timezone.now():
            raise AuthenticationFailed("Access token expired")

        if not _is_stripe_oauth_app(access_token.application):
            raise AuthenticationFailed("Token not issued for Stripe provisioning")

        return (access_token.user, access_token)


def _is_stripe_oauth_app(app) -> bool:
    if app is None:
        return False
    return app.client_id == settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID
