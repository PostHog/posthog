import base64
import hashlib
from datetime import timedelta
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.sessions.backends.db import SessionStore
from django.core.signing import TimestampSigner
from django.test import RequestFactory, override_settings
from django.utils import timezone

from loginas import settings as la_settings
from parameterized import parameterized

from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.api.oauth.views import _impersonator_id_for_request
from posthog.middleware import IMPERSONATION_READ_ONLY_SESSION_KEY
from posthog.models import OAuthApplication, User
from posthog.models.oauth import OAuthAccessToken, OAuthGrant, OAuthRefreshToken

TEST_OAUTH2_PROVIDER_WITH_RSA = {
    **settings.OAUTH2_PROVIDER,
    "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
}


@override_settings(OAUTH2_PROVIDER=TEST_OAUTH2_PROVIDER_WITH_RSA)
class TestImpersonationOAuthRevocation(BaseTest):
    def test_user_logged_out_revokes_only_impersonated_tokens(self) -> None:
        admin = User.objects.create_user(email="admin@posthog.com", password="x", first_name="A")
        admin.is_staff = True
        admin.save()
        target = User.objects.create_user(email="customer@example.com", password="x", first_name="C")

        app = OAuthApplication.objects.create(
            client_id="test-client-id",
            redirect_uris="http://localhost/cb",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            organization=self.organization,
        )

        impersonated_access = OAuthAccessToken.objects.create(
            user=target,
            application=app,
            token="imp-access",
            scope="feature_flag:read",
            expires="2099-01-01T00:00:00Z",
            scoped_teams=[],
            scoped_organizations=[],
            impersonated_by=admin,
        )
        impersonated_refresh = OAuthRefreshToken.objects.create(
            user=target,
            application=app,
            token="imp-refresh",
            access_token=impersonated_access,
            scoped_teams=[],
            scoped_organizations=[],
            impersonated_by=admin,
        )
        impersonated_grant = OAuthGrant.objects.create(
            user=target,
            application=app,
            code="imp-code",
            expires="2099-01-01T00:00:00Z",
            redirect_uri="http://localhost/cb",
            scope="feature_flag:read",
            code_challenge="x" * 43,
            code_challenge_method="S256",
            scoped_teams=[],
            scoped_organizations=[],
            impersonated_by=admin,
        )

        customer_owned = OAuthAccessToken.objects.create(
            user=target,
            application=app,
            token="customer-access",
            scope="feature_flag:write",
            expires="2099-01-01T00:00:00Z",
            scoped_teams=[],
            scoped_organizations=[],
            impersonated_by=None,
        )

        request = RequestFactory().get("/")
        request.session = SessionStore()
        request.session[la_settings.USER_SESSION_FLAG] = TimestampSigner().sign(str(admin.pk))
        request.user = target

        with patch("posthog.helpers.impersonation.is_impersonated_session", return_value=True):
            logout(request)

        self.assertFalse(OAuthAccessToken.objects.filter(pk=impersonated_access.pk).exists())
        revived_refresh = OAuthRefreshToken.objects.get(pk=impersonated_refresh.pk)
        self.assertIsNotNone(revived_refresh.revoked)
        self.assertFalse(OAuthGrant.objects.filter(pk=impersonated_grant.pk).exists())

        self.assertTrue(OAuthAccessToken.objects.filter(pk=customer_owned.pk).exists())


@override_settings(OAUTH2_PROVIDER=TEST_OAUTH2_PROVIDER_WITH_RSA)
class TestImpersonationOAuthTokenIssuance(APIBaseTest):
    """Code-exchange flow: tokens minted from an impersonation-tagged grant must be
    short-lived and refresh-less, so they expire at the impersonation idle timeout
    even when the staff user never explicitly logs out. The 30min cap + refresh
    suppression key off the grant's `impersonated_by_id` alone, which is set during
    `/oauth/authorize` for both read-only and read-write impersonation — so this
    test implicitly covers both modes."""

    def test_code_exchange_caps_expiry_and_suppresses_refresh_for_impersonation_grants(self) -> None:
        admin = User.objects.create_user(email="admin@posthog.com", password="x", first_name="A")
        admin.is_staff = True
        admin.save()

        app = OAuthApplication.objects.create(
            name="App",
            client_id="impersonation-test-client",
            client_secret="impersonation-test-secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )

        # PKCE bits — `S256` over a fixed verifier. The validator only checks the
        # challenge round-trips; the exact values don't matter.
        verifier = "impersonation-test-verifier"
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).decode("utf-8").replace("=", "")
        )

        grant = OAuthGrant.objects.create(
            application=app,
            user=self.user,
            code="impersonation-grant-code",
            code_challenge=challenge,
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=10),
            redirect_uri="https://example.com/callback",
            scope="feature_flag:read",
            scoped_organizations=[str(self.organization.id)],
            scoped_teams=[],
            impersonated_by=admin,
        )

        response = self.client.post(
            "/oauth/token/",
            data=urlencode(
                {
                    "grant_type": "authorization_code",
                    "client_id": app.client_id,
                    "client_secret": "impersonation-test-secret",
                    "redirect_uri": "https://example.com/callback",
                    "code_verifier": verifier,
                    "code": grant.code,
                }
            ),
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()

        self.assertIn("access_token", body)
        self.assertNotIn("refresh_token", body)
        self.assertEqual(body["expires_in"], settings.IMPERSONATION_IDLE_TIMEOUT_SECONDS)

        access_token = OAuthAccessToken.objects.get(token=body["access_token"])
        self.assertEqual(access_token.impersonated_by_id, admin.pk)
        self.assertFalse(OAuthRefreshToken.objects.filter(application=app, user=self.user).exists())


class TestImpersonatorIdResolution(BaseTest):
    """The 30min cap, refresh suppression, and revocation-on-logout protections key off
    the impersonator stamp set by `_impersonator_id_for_request` during `/oauth/authorize`.
    That stamp must be set for *any* impersonation session — read-only or read-write —
    so write-mode impersonation gets the same gating as read-only (only the scope
    downgrade is read-only-specific)."""

    @parameterized.expand(
        [
            ("read_only", True),
            ("read_write", False),
        ]
    )
    def test_impersonator_id_set_for_both_impersonation_modes(self, _name: str, read_only: bool) -> None:
        admin = User.objects.create_user(email="admin@posthog.com", password="x", first_name="A")
        admin.is_staff = True
        admin.save()
        target = User.objects.create_user(email="customer@example.com", password="x", first_name="C")

        request = RequestFactory().get("/")
        request.session = SessionStore()
        request.session[la_settings.USER_SESSION_FLAG] = TimestampSigner().sign(str(admin.pk))
        if read_only:
            request.session[IMPERSONATION_READ_ONLY_SESSION_KEY] = True
        request.user = target

        self.assertEqual(_impersonator_id_for_request(request), admin.pk)

    def test_impersonator_id_none_when_not_impersonating(self) -> None:
        target = User.objects.create_user(email="customer@example.com", password="x", first_name="C")
        request = RequestFactory().get("/")
        request.session = SessionStore()
        request.user = target

        self.assertIsNone(_impersonator_id_for_request(request))
