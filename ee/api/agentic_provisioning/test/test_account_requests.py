import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework.response import Response

from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase


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
        assert user.organization.name == expected_org_name

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

    def test_pkce_partner_new_user_still_gets_direct_code(self):
        payload = self._account_request_payload(email="brand_new@example.com")
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]

    def test_pkce_partner_with_skip_consent_existing_user_gets_direct_code(self):
        self.pkce_partner.provisioning_skip_existing_user_consent = True
        self.pkce_partner.save()
        User.objects.create_and_join(
            organization=self.organization, email="existing@example.com", password="testpass", first_name="Existing"
        )
        payload = self._account_request_payload()
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]
        # Consent path would return a requires_auth payload with redirect URL; absence proves consent was skipped.
        assert "requires_auth" not in data

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
