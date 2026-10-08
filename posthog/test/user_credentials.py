"""A valid credential for every authentication class whose `authenticate()` returns a `User`.

`posthog/test/repo_invariants/test_authentication_credential_types.py` fails when such a class has no
entry here. `posthog/api/test/test_authentication.py` uses each credential to check that its class
refuses an inactive or blocked user.
"""

import time
import base64
from collections.abc import Callable
from datetime import timedelta
from typing import cast

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.contrib.auth import get_user, login
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import override_settings
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

import jwt
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.auth import mint_export_renderer_token
from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token, generate_random_token_personal, hash_key_value

from products.exports.backend.models.exported_asset import ExportedAsset

# Takes the running test, so a factory can read its user and team and hold settings for the whole test.
CredentialFactory = Callable[[APIBaseTest], Request]


def _authorization(value: str) -> Request:
    return Request(APIRequestFactory().get("/", HTTP_AUTHORIZATION=value))  # ty: ignore[invalid-return-type]


def _bearer(token: str) -> Request:
    return _authorization(f"Bearer {token}")


def _session(test: APIBaseTest) -> Request:
    django_request = APIRequestFactory().get("/")
    SessionMiddleware(lambda _: HttpResponse()).process_request(django_request)
    login(django_request, test.user, backend="django.contrib.auth.backends.ModelBackend")
    # Load the user when authenticate() runs, as AuthenticationMiddleware does, so the test can deactivate it first.
    django_request.user = cast(User, SimpleLazyObject(lambda: get_user(django_request)))
    return Request(django_request)  # ty: ignore[invalid-return-type]


def _personal_api_key(user: User) -> tuple[PersonalAPIKey, str]:
    value = generate_random_token_personal()
    key = PersonalAPIKey.objects.create(label="Test", user=user, secure_value=hash_key_value(value), scopes=["*"])
    return key, value


def _oauth_access_token(user: User, **application_fields: object) -> OAuthAccessToken:
    application = OAuthApplication.objects.create(
        **{
            "name": "Test app",
            "client_id": generate_random_token(),
            "client_secret": generate_random_token(),
            "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://example.com/callback",
            "user": user,
            "hash_client_secret": True,
            "algorithm": "RS256",
            **application_fields,
        }
    )
    return OAuthAccessToken.objects.create(
        user=user,
        application=application,
        token=f"pha_{generate_random_token_personal()}",
        scope="*",
        expires=timezone.now() + timedelta(hours=1),
    )


def _delegated(user: User, **claims: int | str) -> Request:
    return _bearer(encode_jwt({"id": user.id, **claims}, timedelta(minutes=5), PosthogJwtAudience.DELEGATED_USER))


def _export_renderer(test: APIBaseTest) -> Request:
    asset = ExportedAsset.objects.create(
        team=test.team,
        created_by=test.user,
        export_format=ExportedAsset.ExportFormat.PNG,
        export_context={"session_recording_id": "recording-id"},
    )
    return _bearer(
        mint_export_renderer_token(
            user_id=test.user.id, team_id=test.team.id, exported_asset_id=asset.id, scope="session_recording:read"
        )
    )


def _id_jag(test: APIBaseTest) -> Request:
    test.organization.available_product_features = [
        {"key": AvailableFeature.XAA_AUTHENTICATION, "name": "XAA Authentication"}
    ]
    test.organization.save()
    now = int(time.time())
    claims = {
        "iss": settings.SITE_URL,
        "aud": settings.SITE_URL,
        "sub": f"example.com:{test.user.email}",
        "user_uuid": str(test.user.uuid),
        "client_id": "test-client",
        "scope": "user:read",
        "org_id": str(test.organization.id),
        "iat": now,
        "exp": now + 300,
    }
    return _bearer(jwt.encode(claims, settings.OIDC_RSA_PRIVATE_KEY, algorithm="RS256", headers={"typ": "at+jwt"}))


def _livestream(test: APIBaseTest) -> Request:
    claims = {
        "user_id": test.user.id,
        "team_id": test.team.id,
        "organization_id": str(test.organization.id),
        "api_token": test.team.api_token,
    }
    return _bearer(encode_jwt(claims, timedelta(minutes=5), PosthogJwtAudience.LIVESTREAM))


def _provisioning_partner(test: APIBaseTest) -> Request:
    partner_config = ProvisioningConfig(active=True, can_provision_resources=True).model_dump(mode="json")
    access_token = _oauth_access_token(test.user, is_provisioning_partner=True, _provisioning_config=partner_config)
    return _bearer(access_token.token)


def _stripe(test: APIBaseTest) -> Request:
    access_token = _oauth_access_token(test.user)
    test.enterContext(override_settings(STRIPE_POSTHOG_OAUTH_CLIENT_ID=access_token.application.client_id))
    return _bearer(access_token.token)


def _git_basic(test: APIBaseTest) -> Request:
    credentials = base64.b64encode(f"x-access-token:{_personal_api_key(test.user)[1]}".encode()).decode()
    return _authorization(f"Basic {credentials}")


USER_CREDENTIALS: dict[str, CredentialFactory] = {
    "ee.api.agentic_provisioning.authentication.ProvisioningBearerAuthentication": _provisioning_partner,
    "ee.partners.stripe.api.provisioning.authentication.StripeBearerAuthentication": _stripe,
    "posthog.api.livestream.LivestreamAuthentication": _livestream,
    "posthog.auth.DelegatedOAuthAccessTokenAuthentication": lambda test: _delegated(
        test.user, oauth_access_token_id=str(_oauth_access_token(test.user).id)
    ),
    "posthog.auth.DelegatedPersonalAPIKeyAuthentication": lambda test: _delegated(
        test.user, personal_api_key_id=_personal_api_key(test.user)[0].id
    ),
    "posthog.auth.ExportRendererAuthentication": _export_renderer,
    "posthog.auth.IDJagAccessTokenAuthentication": _id_jag,
    "posthog.auth.JwtAuthentication": lambda test: _bearer(
        encode_jwt({"id": test.user.id}, timedelta(minutes=5), PosthogJwtAudience.IMPERSONATED_USER)
    ),
    "posthog.auth.OAuthAccessTokenAuthentication": lambda test: _bearer(_oauth_access_token(test.user).token),
    "posthog.auth.PersonalAPIKeyAuthentication": lambda test: _bearer(_personal_api_key(test.user)[1]),
    "posthog.auth.SessionAuthentication": _session,
    "products.customer_analytics.backend.presentation.views.external.ExternalAccountPersonalAPIKeyAuthentication": lambda test: (
        _bearer(_personal_api_key(test.user)[1])
    ),
    "products.skills.backend.marketplace.auth.MarketplaceGitBasicAuthentication": _git_basic,
}
