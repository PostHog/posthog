from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError
from django.http import JsonResponse
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.oauth import OAuthApplication
from posthog.models.user import User

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.constants import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX
from ee.api.agentic_provisioning.test.base import ProvisioningTestBase, provisioning_config

ACCOUNT_REQUESTS_URL = "/api/agentic/provisioning/account_requests"
VALID_CODE_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class TestAccountRequests(ProvisioningTestBase):
    def _account_request_payload(self, **overrides):
        payload = {
            "id": "acctreq_test123",
            "email": "newuser@example.com",
            "scopes": ["query:read", "project:read"],
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
        }
        payload.update(overrides)
        return payload

    def _post_account_request(self, payload):
        return self._post_with_client_secret(ACCOUNT_REQUESTS_URL, payload)

    def test_no_identified_partner_returns_401(self):
        res = self._post_api(ACCOUNT_REQUESTS_URL, self._account_request_payload())
        assert res.status_code == 401
        data = res.json()
        assert data["type"] == "error"
        assert data["error"]["code"] == "unauthorized"

    def test_new_user_returns_oauth_type_with_code(self):
        res = self._post_account_request(self._account_request_payload())
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == "acctreq_test123"
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]
        assert len(data["oauth"]["code"]) > 0
        assert User.objects.filter(email="newuser@example.com").exists()

    def test_new_user_creates_org_and_team(self):
        self._post_account_request(self._account_request_payload())
        user = User.objects.get(email="newuser@example.com")
        assert user.organization is not None
        assert user.team is not None

    def test_new_user_starts_unverified(self):
        # Partner-asserted email ownership is not trusted: the user must prove they own
        # the inbox before any session is issued (see agentic_login).
        self._post_account_request(self._account_request_payload())
        user = User.objects.get(email="newuser@example.com")
        assert user.is_email_verified is False

    def test_new_user_auth_code_cached_with_issued_at(self):
        res = self._post_account_request(self._account_request_payload())
        code = res.json()["oauth"]["code"]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data is not None
        # Without issued_at the code exchange fails closed once the app is ever session-revoked,
        # which would block every new user. See _exchange_authorization_code's revoke guard.
        assert "issued_at" in code_data
        datetime.fromisoformat(code_data["issued_at"])

    def test_existing_user_requires_consent_even_for_skip_consent_partner(self):
        # No partner may silently link a pre-existing account. A verified client secret proves
        # the partner controls itself, never that it controls this email.
        self.partner.update_provisioning(skip_existing_user_consent=True)

        payload = self._account_request_payload(email=self.user.email, code_challenge=VALID_CODE_CHALLENGE)
        res = self._post_account_request(payload)

        assert res.status_code == 200
        assert res.json()["type"] == "requires_auth"

    def test_expired_request_returns_400(self):
        payload = self._account_request_payload(expires_at=(timezone.now() - timedelta(minutes=1)).isoformat())
        res = self._post_account_request(payload)
        assert res.status_code == 400
        assert res.json()["type"] == "error"

    def test_missing_email_returns_400(self):
        payload = self._account_request_payload()
        del payload["email"]
        res = self._post_account_request(payload)
        assert res.status_code == 400

    def test_new_user_with_name(self):
        self._post_account_request(self._account_request_payload(name="Jane Doe", email="jane@example.com"))
        user = User.objects.get(email="jane@example.com")
        assert user.first_name == "Jane"

    @parameterized.expand(
        [
            ("with_name", {"region": "US", "organization_name": "Acme Corp"}, "Acme Corp"),
            ("without_name", {"region": "US"}, "Test Provisioning Partner (orgname@example.com)"),
        ]
    )
    def test_new_user_organization_name(self, _name, config, expected_org_name):
        self._post_account_request(self._account_request_payload(email="orgname@example.com", configuration=config))
        user = User.objects.get(email="orgname@example.com")
        org = user.organization
        assert org is not None
        assert org.name == expected_org_name

    @parameterized.expand(
        [
            ("us_instance_eu_region", "US", "EU", "eu.posthog.com"),
            ("eu_instance_us_region", "EU", "US", "us.posthog.com"),
        ]
    )
    @patch("ee.api.agentic_provisioning.region_proxy._proxy_to_region")
    def test_region_mismatch_proxies_to_other_region(self, _name, deployment, region, expected_host, mock_proxy):
        mock_proxy.return_value = JsonResponse({"type": "oauth", "oauth": {"code": "proxied"}})
        payload = self._account_request_payload(configuration={"region": region})
        with override_settings(CLOUD_DEPLOYMENT=deployment):
            res = self._post_account_request(payload)
        assert res.status_code == 200
        mock_proxy.assert_called_once()
        assert mock_proxy.call_args[0][1] == expected_host

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_matching_region_succeeds(self):
        payload = self._account_request_payload(configuration={"region": "US"})
        res = self._post_account_request(payload)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    @patch("ee.api.agentic_provisioning.accounts.User.objects.bootstrap", side_effect=IntegrityError)
    def test_integrity_error_with_existing_user_falls_back(self, _mock_bootstrap):
        User.objects.create_and_join(
            organization=self.organization, email="race@example.com", password="testpass", first_name="Race"
        )
        payload = self._account_request_payload(email="race@example.com", code_challenge=VALID_CODE_CHALLENGE)
        res = self._post_account_request(payload)
        assert res.status_code == 200
        # The race fell back to the existing-user path; without trust proof for that user
        # the partner is sent through consent rather than getting a silent code.
        assert res.json()["type"] == "requires_auth"

    @patch("ee.api.agentic_provisioning.accounts.User.objects.bootstrap", side_effect=IntegrityError)
    def test_integrity_error_without_existing_user_returns_500(self, _mock_bootstrap):
        payload = self._account_request_payload(email="ghost@example.com")
        res = self._post_account_request(payload)
        assert res.status_code == 500
        assert res.json()["error"]["code"] == "account_creation_failed"

    @patch("ee.api.agentic_provisioning.accounts.capture_provisioning_event")
    def test_new_user_capture_includes_team_id(self, mock_capture_event):
        res = self._post_account_request(self._account_request_payload(email="capture@example.com"))
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
        assert kwargs["partner"] == self.partner


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
            is_provisioning_partner=True,
            _provisioning_config=provisioning_config(
                active=True, can_create_accounts=True, can_provision_resources=True
            ),
        )

    def _post_as_pkce_partner(self, data: dict):
        return self._post_api(ACCOUNT_REQUESTS_URL, data)

    def _account_request_payload(self, **overrides):
        payload = {
            "id": "acctreq_pkce_test",
            "email": "existing@example.com",
            "scopes": ["query:read"],
            "client_id": "pkce-test-partner",
            "code_challenge": VALID_CODE_CHALLENGE,
            "code_challenge_method": "S256",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
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

    @patch("ee.api.agentic_provisioning.accounts.capture_provisioning_event")
    def test_pkce_partner_new_user_capture_attributes_client(self, mock_capture_event):
        payload = self._account_request_payload(email="attributed@example.com")
        res = self._post_as_pkce_partner(payload)
        assert res.status_code == 200

        new_user_calls = [
            call for call in mock_capture_event.call_args_list if call.args[:2] == ("account_request", "new_user")
        ]
        assert len(new_user_calls) == 1
        assert new_user_calls[0].kwargs["partner"] == self.pkce_partner

    @patch("ee.api.agentic_provisioning.accounts.report_user_signed_up")
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
        self.pkce_partner.update_provisioning(skip_existing_user_consent=True)
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


class TestCaptureProvisioningEvent(ProvisioningTestBase):
    def _make_partner(self) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id="attribution-test",
            name="Attribution Test Client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
        )

    @parameterized.expand([("with_partner", True), ("no_partner", False)])
    @patch("ee.api.agentic_provisioning.analytics.posthoganalytics.capture")
    def test_partner_attribution(self, _name, expects_client, mock_capture):
        partner = self._make_partner() if expects_client else None
        capture_provisioning_event("account_request", "new_user", partner=partner, team_id=42)

        props = mock_capture.call_args.kwargs["properties"]
        if expects_client:
            assert partner is not None
            assert props["client_name"] == "Attribution Test Client"
            assert props["partner_id"] == str(partner.id)
        else:
            assert "client_name" not in props
            assert "partner_id" not in props
