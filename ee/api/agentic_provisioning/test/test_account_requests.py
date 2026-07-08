import json
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework.response import Response

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX
from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase
from ee.api.agentic_provisioning.views import _capture_provisioning_event

HMAC_PARTNER_SECRET = "test_hmac_partner_secret"


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestAccountRequests(ProvisioningTestBase):
    def _account_request_payload(self, **overrides):
        payload = {
            "id": "acctreq_test123",
            "object": "account_request",
            "email": "newuser@example.com",
            "scopes": ["query:read", "project:read"],
            "client_capabilities": ["browser"],
            "confirmation_secret": "cs_test_secret",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {
                "type": "stripe",
                "stripe": {
                    "organisation": "org_stripe_123",
                    "account": "acct_stripe_456",
                },
            },
        }
        payload.update(overrides)
        return payload

    def test_new_user_returns_oauth_type_with_code(self):
        payload = self._account_request_payload()
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == "acctreq_test123"
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]
        assert len(data["oauth"]["code"]) > 0
        assert User.objects.filter(email="newuser@example.com").exists()

    def test_new_user_creates_org_and_team(self):
        payload = self._account_request_payload()
        self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        user = User.objects.get(email="newuser@example.com")
        assert user.organization is not None
        assert user.team is not None

    def test_new_user_starts_unverified(self):
        # Partner-asserted email ownership is not trusted: the user must prove they own
        # the inbox before any session is issued (see agentic_login).
        payload = self._account_request_payload()
        self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        user = User.objects.get(email="newuser@example.com")
        assert user.is_email_verified is False

    def test_new_user_auth_code_cached_with_issued_at(self):
        payload = self._account_request_payload()
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        code = res.json()["oauth"]["code"]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data is not None
        # Without issued_at the code exchange fails closed once the app is ever session-revoked,
        # which would block every new user. See _exchange_authorization_code's revoke guard.
        assert "issued_at" in code_data
        datetime.fromisoformat(code_data["issued_at"])

    def test_existing_user_returns_oauth_type_with_code(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload(email="existing@example.com")
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == "acctreq_test123"
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]

    def test_existing_user_auth_code_cached_with_team(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload(email="existing@example.com")
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        code = res.json()["oauth"]["code"]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data is not None
        assert code_data["stripe_account_id"] == "acct_stripe_456"
        assert code_data["team_id"] == self.team.id
        assert code_data["region"] == "US"

    def test_existing_user_with_requested_team_id(self):
        user = User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        second_team = Team.objects.create_with_data(initiating_user=user, organization=self.organization)
        payload = self._account_request_payload(
            email="existing@example.com",
            configuration={"team_id": second_team.id},
        )
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        code = res.json()["oauth"]["code"]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data["team_id"] == second_team.id

    def test_existing_user_with_invalid_team_id_returns_400(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload(
            email="existing@example.com",
            configuration={"team_id": 999999},
        )
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "team_resolution_failed"

    def test_existing_user_with_non_numeric_team_id_returns_400(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload(
            email="existing@example.com",
            configuration={"team_id": "abc"},
        )
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_request"

    def test_existing_user_with_inaccessible_team_id_returns_400(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        payload = self._account_request_payload(
            email="existing@example.com",
            configuration={"team_id": other_team.id},
        )
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "team_resolution_failed"

    def test_existing_user_multi_team_creates_new_project(self):
        user = User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        Team.objects.create_with_data(initiating_user=user, organization=self.organization)
        team_count_before = Team.objects.filter(organization=self.organization, is_demo=False).count()
        payload = self._account_request_payload(email="existing@example.com")
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        team_count_after = Team.objects.filter(organization=self.organization, is_demo=False).count()
        assert team_count_after == team_count_before + 1

    def test_expired_request_returns_400(self):
        payload = self._account_request_payload(expires_at=(timezone.now() - timedelta(minutes=1)).isoformat())
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 400
        assert res.json()["type"] == "error"

    def test_missing_email_returns_400(self):
        payload = self._account_request_payload()
        del payload["email"]
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 400

    def test_missing_stripe_account_returns_400(self):
        payload = self._account_request_payload()
        del payload["orchestrator"]
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_request"

    def test_invalid_signature_returns_401(self):
        payload = self._account_request_payload()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=payload,
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 401

    def test_new_user_with_name(self):
        payload = self._account_request_payload(name="Jane Doe", email="jane@example.com")
        self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        user = User.objects.get(email="jane@example.com")
        assert user.first_name == "Jane"

    @parameterized.expand(
        [
            ("with_name", {"region": "US", "organization_name": "Acme Corp"}, "Acme Corp"),
            ("without_name", {"region": "US"}, "Stripe (orgname@example.com)"),
        ]
    )
    def test_new_user_organization_name(self, _name, config, expected_org_name):
        payload = self._account_request_payload(email="orgname@example.com", configuration=config)
        self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        user = User.objects.get(email="orgname@example.com")
        org = user.organization
        assert org is not None
        assert org.name == expected_org_name

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("ee.api.agentic_provisioning.region_proxy._proxy_to_region")
    def test_region_mismatch_proxies_to_other_region(self, mock_proxy):
        mock_proxy.return_value = Response({"type": "oauth", "oauth": {"code": "proxied"}})
        payload = self._account_request_payload(configuration={"region": "EU"})
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        mock_proxy.assert_called_once()
        args = mock_proxy.call_args
        assert args[0][1] == "eu.posthog.com"

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_matching_region_succeeds(self):
        payload = self._account_request_payload(configuration={"region": "US"})
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    @override_settings(CLOUD_DEPLOYMENT="EU")
    @patch("ee.api.agentic_provisioning.region_proxy._proxy_to_region")
    def test_eu_instance_proxies_us_region(self, mock_proxy):
        mock_proxy.return_value = Response({"type": "oauth", "oauth": {"code": "proxied"}})
        payload = self._account_request_payload(configuration={"region": "US"})
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        mock_proxy.assert_called_once()
        args = mock_proxy.call_args
        assert args[0][1] == "us.posthog.com"

    def test_no_region_defaults_to_us_and_succeeds(self):
        payload = self._account_request_payload()
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200

    @patch("ee.api.agentic_provisioning.views.User.objects.bootstrap", side_effect=IntegrityError)
    def test_integrity_error_with_existing_user_falls_back(self, _mock_bootstrap):
        User.objects.create_and_join(
            organization=self.organization, email="race@example.com", password="testpass", first_name="Race"
        )
        payload = self._account_request_payload(email="race@example.com")
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    @patch("ee.api.agentic_provisioning.views.User.objects.bootstrap", side_effect=IntegrityError)
    def test_integrity_error_without_existing_user_returns_500(self, _mock_bootstrap):
        payload = self._account_request_payload(email="ghost@example.com")
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 500
        assert res.json()["error"]["code"] == "account_creation_failed"

    def test_hmac_partner_existing_user_still_gets_direct_code(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload(email="existing@example.com")
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        assert "code" in res.json()["oauth"]

    @patch("ee.api.agentic_provisioning.views._capture_provisioning_event")
    def test_new_user_capture_includes_team_id(self, mock_capture_event):
        payload = self._account_request_payload(email="capture@example.com")
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200

        user = User.objects.get(email="capture@example.com")
        team = user.team
        assert team is not None

        new_user_calls = [
            call for call in mock_capture_event.call_args_list if call.args[:2] == ("account_request", "new_user")
        ]
        assert len(new_user_calls) == 1
        kwargs = new_user_calls[0].kwargs
        assert kwargs["team_id"] == team.id
        # Stripe HMAC path has no OAuthApplication partner, so there's no client to attribute.
        assert kwargs["partner"] is None

    @patch("ee.api.agentic_provisioning.views.report_user_signed_up")
    def test_new_user_emits_signup_event(self, mock_signup):
        payload = self._account_request_payload(email="signupevent@example.com")
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
        assert res.status_code == 200

        assert mock_signup.call_count == 1
        kwargs = mock_signup.call_args.kwargs
        assert kwargs["backend_processor"] == "AgenticProvisioning"
        assert kwargs["is_organization_first_user"] is True
        # Stripe HMAC path has no OAuthApplication, so no client name.
        assert kwargs["social_provider"] == ""


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestPKCEPartnerExistingUserConsent(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self.pkce_partner = OAuthApplication.objects.create(
            client_id="pkce-test-partner",
            name="PKCE Test Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_first_party=True,
            provisioning_auth_method="pkce",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

    def _post_as_pkce_partner(self, data: dict):
        body = json.dumps(data).encode()
        return self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )

    def _account_request_payload(self, **overrides):
        payload = {
            "id": "acctreq_pkce_test",
            "email": "existing@example.com",
            "scopes": ["query:read"],
            "client_id": "pkce-test-partner",
            "confirmation_secret": "cs_test",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {"type": "test", "account": "acct_123"},
        }
        payload.update(overrides)
        return payload

    def test_pkce_partner_existing_user_returns_requires_auth(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload()
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        assert "url" in data["requires_auth"]
        assert "/api/agentic/authorize" in data["requires_auth"]["url"]

    def test_pkce_partner_existing_user_creates_pending_auth(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload()
        res = self._post_as_pkce_partner(payload)
        data = res.json()

        url = data["requires_auth"]["url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        pending = cache.get(f"{PENDING_AUTH_CACHE_PREFIX}{state}")
        assert pending is not None
        assert pending["email"] == "existing@example.com"
        assert pending["partner_id"] == str(self.pkce_partner.id)
        assert pending["scopes"] == ["query:read"]
        assert pending["consent_required"] is True

    def test_pkce_partner_within_ceiling_creates_pending_auth(self):
        self.pkce_partner.scopes = ["query:read", "insight:read"]
        self.pkce_partner.save()
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload(scopes=["query:read"])
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200
        assert res.json()["type"] == "requires_auth"

    def test_pkce_partner_outside_ceiling_returns_invalid_scope(self):
        self.pkce_partner.scopes = ["query:read"]
        self.pkce_partner.save()
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload(scopes=["query:read", "insight:write"])
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_scope"

    def test_pkce_partner_new_user_still_gets_direct_code(self):
        payload = self._account_request_payload(email="brand_new@example.com")
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]

    @patch("ee.api.agentic_provisioning.views._capture_provisioning_event")
    def test_pkce_partner_new_user_capture_attributes_client(self, mock_capture_event):
        payload = self._account_request_payload(email="attributed@example.com")
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200

        new_user_calls = [
            call for call in mock_capture_event.call_args_list if call.args[:2] == ("account_request", "new_user")
        ]
        assert len(new_user_calls) == 1
        assert new_user_calls[0].kwargs["partner"] == self.pkce_partner

    @patch("ee.api.agentic_provisioning.views.report_user_signed_up")
    def test_pkce_partner_new_user_emits_signup_event_with_client(self, mock_signup):
        payload = self._account_request_payload(email="pkce_signup@example.com")
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200

        assert mock_signup.call_count == 1
        kwargs = mock_signup.call_args.kwargs
        assert kwargs["backend_processor"] == "AgenticProvisioning"
        assert kwargs["is_organization_first_user"] is True
        assert kwargs["social_provider"] == self.pkce_partner.name

    def test_pkce_partner_with_skip_consent_existing_user_requires_consent(self):
        # A public PKCE caller is identified only by a client_id anyone can send, so even with
        # skip_existing_user_consent it must not silently mint for an existing account — it has
        # no proof it controls the partner or the account.
        self.pkce_partner.provisioning_skip_existing_user_consent = True
        self.pkce_partner.save()
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload()
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        assert "oauth" not in data

    def test_pkce_partner_missing_code_challenge_returns_400(self):
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload()
        del payload["code_challenge"]
        del payload["code_challenge_method"]
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_request"

    @parameterized.expand(
        [
            ("too_short", "abc"),
            ("too_long", "A" * 129),
            ("invalid_chars", "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw!cM"),
        ]
    )
    def test_pkce_partner_malformed_code_challenge_returns_400(self, _name, challenge):
        payload = self._account_request_payload(code_challenge=challenge)
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_request"
        assert "code_challenge" in res.json()["error"]["message"]


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestSilentRemintRequiresTrustProof(ProvisioningTestBase):
    """A partner with skip_existing_user_consent=True can only mint silently for an
    existing user when the caller proved a prior trust relationship with that user
    (live partner credential for HMAC, the user's own token for bearer). Otherwise
    the consent screen is required. This holds whether or not the user has reviewed
    their credentials: an unreviewed account is still a pre-existing account that a
    caller must not be able to silently link."""

    def setUp(self):
        super().setUp()
        self.partner = OAuthApplication.objects.create(
            client_id="silent-partner",
            name="Silent Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_first_party=True,
            provisioning_auth_method="pkce",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
            provisioning_skip_existing_user_consent=True,
        )
        self.other_partner = OAuthApplication.objects.create(
            client_id="other-partner",
            name="Other Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://other.example.com/callback",
            algorithm="RS256",
            is_first_party=True,
            provisioning_auth_method="pkce",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
            provisioning_skip_existing_user_consent=True,
        )
        self.hmac_partner = OAuthApplication.objects.create(
            client_id="hmac-partner",
            name="HMAC Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://hmac.example.com/callback",
            algorithm="RS256",
            is_first_party=True,
            provisioning_auth_method="hmac",
            provisioning_signing_secret=HMAC_PARTNER_SECRET,
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
            provisioning_skip_existing_user_consent=True,
        )
        self.bearer_partner = OAuthApplication.objects.create(
            client_id="bearer-partner",
            name="Bearer Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://bearer.example.com/callback",
            algorithm="RS256",
            is_first_party=True,
            provisioning_auth_method="bearer",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
            provisioning_skip_existing_user_consent=True,
        )

    def _post_as_partner(self, data: dict, client_id: str = "silent-partner"):
        payload = {**data, "client_id": client_id}
        body = json.dumps(payload).encode()
        return self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )

    def _post_as_hmac_partner(self, data: dict):
        body = json.dumps(data).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_PARTNER_SECRET, ts, body)
        return self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )

    def _post_as_bearer_partner(self, data: dict, token: str):
        body = json.dumps(data).encode()
        return self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_API_VERSION="0.1d",
        )

    def _account_request_payload(self, **overrides):
        payload = {
            "id": "acctreq_silent_test",
            "email": "existing@example.com",
            "scopes": ["query:read"],
            "confirmation_secret": "cs_test",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {"type": "test", "account": "acct_123"},
        }
        payload.update(overrides)
        return payload

    def _make_user(self, *, credentials_reviewed: bool) -> User:
        user = User.objects.create_and_join(
            organization=self.organization,
            email="existing@example.com",
            password="testpass",
            first_name="Existing",
        )
        user.credentials_reviewed_at = timezone.now() if credentials_reviewed else None
        user.save(update_fields=["credentials_reviewed_at"])
        return user

    def _make_live_access_token(self, user: User, partner: OAuthApplication) -> OAuthAccessToken:
        return OAuthAccessToken.objects.create(
            user=user,
            application=partner,
            token=f"tok_{user.id}_{partner.id}",
            expires=timezone.now() + timedelta(hours=1),
            scope="query:read",
        )

    def _make_live_refresh_token(self, user: User, partner: OAuthApplication) -> OAuthRefreshToken:
        return OAuthRefreshToken.objects.create(
            user=user,
            application=partner,
            token=f"rtok_{user.id}_{partner.id}",
            revoked=None,
        )

    def _make_revoked_refresh_token(self, user: User, partner: OAuthApplication) -> OAuthRefreshToken:
        return OAuthRefreshToken.objects.create(
            user=user,
            application=partner,
            token=f"rtok_{user.id}_{partner.id}",
            revoked=timezone.now(),
        )

    def test_unreviewed_existing_user_pkce_requires_consent(self):
        # A public PKCE caller never proves control of the partner, so it must not mint
        # silently for an existing account — even an unreviewed one, whose email may belong
        # to a direct signup the caller has no relationship with.
        self._make_user(credentials_reviewed=False)
        res = self._post_as_partner(self._account_request_payload())
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        assert "oauth" not in data

    @parameterized.expand(
        [
            ("live_access_token", lambda self, user: self._make_live_access_token(user, self.hmac_partner)),
            ("live_refresh_token", lambda self, user: self._make_live_refresh_token(user, self.hmac_partner)),
        ]
    )
    def test_reviewed_user_with_live_credential_from_authenticated_caller_silent_still_works(
        self, _name, setup_credential
    ):
        user = self._make_user(credentials_reviewed=True)
        setup_credential(self, user)
        res = self._post_as_hmac_partner(self._account_request_payload())
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]

    @parameterized.expand([("reviewed", True), ("unreviewed", False)])
    def test_pkce_caller_with_live_credential_requires_consent(self, _name, reviewed):
        # A public PKCE caller is unauthenticated, so an existing live credential for the
        # claimed client_id is not proof the caller controls the partner. It must not unlock
        # the silent path for an existing user, in either review state.
        user = self._make_user(credentials_reviewed=reviewed)
        self._make_live_access_token(user, self.partner)
        res = self._post_as_partner(self._account_request_payload())
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        assert "oauth" not in data

    @parameterized.expand(
        [
            ("no_credentials", lambda self, user: None),
            (
                "different_partner_credential",
                lambda self, user: self._make_live_access_token(user, self.other_partner),
            ),
            ("only_revoked_token", lambda self, user: self._make_revoked_refresh_token(user, self.partner)),
        ]
    )
    def test_reviewed_user_without_live_caller_credential_falls_through_to_consent(self, _name, setup_credential):
        user = self._make_user(credentials_reviewed=True)
        setup_credential(self, user)
        res = self._post_as_partner(self._account_request_payload())
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        assert "url" in data["requires_auth"]
        assert "/api/agentic/authorize" in data["requires_auth"]["url"]
        assert "oauth" not in data

        url = data["requires_auth"]["url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        pending = cache.get(f"{PENDING_AUTH_CACHE_PREFIX}{state}")
        assert pending is not None
        assert pending["partner_id"] == str(self.partner.id)

    def _mint_bearer_token(self, user: User, partner: OAuthApplication, raw_token: str) -> None:
        OAuthAccessToken.objects.create(
            user=user,
            application=partner,
            token=raw_token,
            expires=timezone.now() + timedelta(hours=1),
            scope="query:read",
        )

    @parameterized.expand([("reviewed", True), ("unreviewed", False)])
    def test_bearer_caller_cannot_remint_for_other_user(self, _name, reviewed):
        # A bearer token only proves the caller holds *some* user's token under the partner's
        # client, not that they control the partner. An attacker holding their own token must
        # not ride a victim's account to mint a code for it, whether or not the victim has
        # reviewed credentials — an unreviewed account is still a pre-existing account.
        victim = self._make_user(credentials_reviewed=reviewed)
        self._make_live_access_token(victim, self.bearer_partner)

        attacker = User.objects.create_and_join(
            organization=self.organization,
            email="attacker@example.com",
            password="testpass",
            first_name="Attacker",
        )
        self._mint_bearer_token(attacker, self.bearer_partner, "attacker_bearer_token")

        res = self._post_as_bearer_partner(self._account_request_payload(), token="attacker_bearer_token")
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        assert "oauth" not in data

    @parameterized.expand([("reviewed", True), ("unreviewed", False)])
    def test_bearer_caller_can_remint_for_own_user(self, _name, reviewed):
        # The legitimate bearer re-link path: the caller presents the user's own token, which
        # is genuine proof of an existing trust relationship, so it stays silent in either state.
        user = self._make_user(credentials_reviewed=reviewed)
        self._mint_bearer_token(user, self.bearer_partner, "owner_bearer_token")

        res = self._post_as_bearer_partner(self._account_request_payload(), token="owner_bearer_token")
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]

    @parameterized.expand([("reviewed", True), ("unreviewed", False)])
    def test_hmac_first_link_existing_user_requires_consent(self, _name, reviewed):
        # HMAC proof is "the partner already holds a live credential for this user". On a first
        # link there is none, so even a trusted HMAC partner must get consent before linking a
        # pre-existing account, regardless of review state.
        self._make_user(credentials_reviewed=reviewed)
        res = self._post_as_hmac_partner(self._account_request_payload())
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        assert "oauth" not in data

    @parameterized.expand([("reviewed", True), ("unreviewed", False)])
    def test_hmac_relink_existing_user_with_live_credential_silent(self, _name, reviewed):
        # Genuine HMAC re-link: the partner holds a live credential for the user, so it may
        # mint silently whether or not the user has reviewed credentials.
        user = self._make_user(credentials_reviewed=reviewed)
        self._make_live_access_token(user, self.hmac_partner)
        res = self._post_as_hmac_partner(self._account_request_payload())
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestCaptureProvisioningEvent(ProvisioningTestBase):
    def _make_partner(self, partner_type: str = "test_partner") -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id=f"attribution-test-{partner_type or 'untyped'}",
            name="Attribution Test Client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            provisioning_partner_type=partner_type,
        )

    @parameterized.expand(
        [
            ("typed_partner", "test_partner", True, "test_partner"),
            ("untyped_partner", "", True, None),
            ("no_partner", None, False, None),
        ]
    )
    @patch("ee.api.agentic_provisioning.views.posthoganalytics.capture")
    def test_partner_attribution(self, _name, partner_type, expects_client, expected_partner_type, mock_capture):
        partner = None if partner_type is None else self._make_partner(partner_type=partner_type)
        _capture_provisioning_event("account_request", "new_user", partner=partner, team_id=42)

        props = mock_capture.call_args.kwargs["properties"]
        if expects_client:
            assert partner is not None
            assert props["client_name"] == "Attribution Test Client"
            assert props["partner_id"] == str(partner.id)
        else:
            assert "client_name" not in props
            assert "partner_id" not in props
        if expected_partner_type is None:
            assert "partner_type" not in props
        else:
            assert props["partner_type"] == expected_partner_type
