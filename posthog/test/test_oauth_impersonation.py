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
from posthog.api.oauth.views import _impersonation_ai_processing_block, _impersonator_id_for_request
from posthog.middleware import IMPERSONATION_READ_ONLY_SESSION_KEY
from posthog.models import OAuthApplication, Organization, OrganizationMembership, Team, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplicationAccessLevel, OAuthGrant, OAuthRefreshToken

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


class TestImpersonationAIProcessingBlock(BaseTest):
    """Organizations that opt out of AI data processing must not be authorizable for any OAuth
    client (the MCP being the motivating case) while a staff member is impersonating a customer.
    Customers authorizing a client themselves are unaffected — they have already consented for
    their own data."""

    def _build_request(self, target: User, *, impersonating: bool) -> RequestFactory:
        request = RequestFactory().get("/")
        request.session = SessionStore()
        if impersonating:
            admin = User.objects.create_user(email="admin@posthog.com", password="x", first_name="A")
            admin.is_staff = True
            admin.save()
            request.session[la_settings.USER_SESSION_FLAG] = TimestampSigner().sign(str(admin.pk))
        request.user = target
        return request

    def _member_of(self, organization: Organization) -> User:
        target = User.objects.create_user(email="customer@example.com", password="x", first_name="C")
        OrganizationMembership.objects.create(user=target, organization=organization)
        return target

    def test_no_block_when_not_impersonating_even_if_disabled(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        target = self._member_of(self.organization)
        request = self._build_request(target, impersonating=False)

        self.assertIsNone(_impersonation_ai_processing_block(request))

    @parameterized.expand([("explicitly_disabled", False), ("unset", None)])
    def test_blocks_impersonation_when_org_not_approved(self, _name: str, value: bool | None) -> None:
        self.organization.is_ai_data_processing_approved = value
        self.organization.save()
        target = self._member_of(self.organization)
        request = self._build_request(target, impersonating=True)

        response = _impersonation_ai_processing_block(request)
        assert response is not None
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"], "access_denied")

    def test_no_block_when_org_approved(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        target = self._member_of(self.organization)
        request = self._build_request(target, impersonating=True)

        self.assertIsNone(_impersonation_ai_processing_block(request))

    def test_no_block_when_disabled_org_out_of_scope(self) -> None:
        approved_org = Organization.objects.create(name="approved", is_ai_data_processing_approved=True)
        disabled_org = Organization.objects.create(name="disabled", is_ai_data_processing_approved=False)
        target = User.objects.create_user(email="customer@example.com", password="x", first_name="C")
        OrganizationMembership.objects.create(user=target, organization=approved_org)
        OrganizationMembership.objects.create(user=target, organization=disabled_org)
        request = self._build_request(target, impersonating=True)

        # Scoping the grant to the approved org only must not be blocked by the unrelated disabled org.
        self.assertIsNone(
            _impersonation_ai_processing_block(
                request,
                access_level=OAuthApplicationAccessLevel.ORGANIZATION.value,
                scoped_organization_ids=[str(approved_org.id)],
            )
        )

    def test_blocks_when_scoped_team_belongs_to_disabled_org(self) -> None:
        disabled_org = Organization.objects.create(name="disabled", is_ai_data_processing_approved=False)
        team = Team.objects.create(organization=disabled_org, name="t")
        target = User.objects.create_user(email="customer@example.com", password="x", first_name="C")
        OrganizationMembership.objects.create(user=target, organization=disabled_org)
        request = self._build_request(target, impersonating=True)

        response = _impersonation_ai_processing_block(
            request,
            access_level=OAuthApplicationAccessLevel.TEAM.value,
            scoped_team_ids=[team.id],
        )
        assert response is not None
        self.assertEqual(response.status_code, 403)
