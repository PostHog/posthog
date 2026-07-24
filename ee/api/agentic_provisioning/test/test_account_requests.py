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
from ee.api.agentic_provisioning.test.base import ProvisioningTestBase
from ee.api.agentic_provisioning.views import _capture_provisioning_event

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

    def _post_account_request(self, payload, token: str | None = None):
        return self._post_with_bearer(ACCOUNT_REQUESTS_URL, payload, token=token or self._get_bearer_token())

    def _silent_partner_token_for(self, user: User) -> str:
        # A skip-consent partner may only mint silently for an existing user when the
        # bearer token belongs to that same user (see _caller_proved_existing_trust).
        self.partner.provisioning_skip_existing_user_consent = True
        self.partner.save(update_fields=["provisioning_skip_existing_user_consent"])
        token = OAuthAccessToken.objects.create(
            user=user,
            application=self.partner,
            token=f"tok_{user.id}",
            expires=timezone.now() + timedelta(hours=1),
            scope="query:read",
        )
        return token.token

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

    def test_existing_user_auth_code_cached_with_team(self):
        token = self._silent_partner_token_for(self.user)
        res = self._post_account_request(self._account_request_payload(email=self.user.email), token=token)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        code = res.json()["oauth"]["code"]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data is not None
        assert code_data["team_id"] == self.team.id
        assert code_data["region"] == "US"
        assert code_data["partner_id"] == str(self.partner.id)

    def test_existing_user_with_requested_team_id(self):
        token = self._silent_partner_token_for(self.user)
        second_team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
        payload = self._account_request_payload(email=self.user.email, configuration={"team_id": second_team.id})
        res = self._post_account_request(payload, token=token)
        assert res.status_code == 200
        code = res.json()["oauth"]["code"]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data["team_id"] == second_team.id

    @parameterized.expand(
        [
            ("nonexistent", 999999, "team_resolution_failed"),
            ("non_numeric", "abc", "invalid_request"),
        ]
    )
    def test_existing_user_with_bad_team_id_returns_400(self, _name, team_id, expected_code):
        token = self._silent_partner_token_for(self.user)
        payload = self._account_request_payload(email=self.user.email, configuration={"team_id": team_id})
        res = self._post_account_request(payload, token=token)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == expected_code

    def test_existing_user_with_inaccessible_team_id_returns_400(self):
        token = self._silent_partner_token_for(self.user)
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        payload = self._account_request_payload(email=self.user.email, configuration={"team_id": other_team.id})
        res = self._post_account_request(payload, token=token)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "team_resolution_failed"

    def test_existing_user_multi_team_creates_new_project(self):
        token = self._silent_partner_token_for(self.user)
        Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
        team_count_before = Team.objects.filter(organization=self.organization, is_demo=False).count()
        res = self._post_account_request(self._account_request_payload(email=self.user.email), token=token)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        team_count_after = Team.objects.filter(organization=self.organization, is_demo=False).count()
        assert team_count_after == team_count_before + 1

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
            ("without_name", {"region": "US"}, "Test_partner (orgname@example.com)"),
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
        mock_proxy.return_value = Response({"type": "oauth", "oauth": {"code": "proxied"}})
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

    @patch("ee.api.agentic_provisioning.views.User.objects.bootstrap", side_effect=IntegrityError)
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

    @patch("ee.api.agentic_provisioning.views.User.objects.bootstrap", side_effect=IntegrityError)
    def test_integrity_error_without_existing_user_returns_500(self, _mock_bootstrap):
        payload = self._account_request_payload(email="ghost@example.com")
        res = self._post_account_request(payload)
        assert res.status_code == 500
        assert res.json()["error"]["code"] == "account_creation_failed"

    @patch("ee.api.agentic_provisioning.views._capture_provisioning_event")
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
            provisioning_auth_method="pkce",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
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


class TestSilentRemintRequiresTrustProof(ProvisioningTestBase):
    """A partner with skip_existing_user_consent=True can only mint silently for an
    existing user when the caller proved a prior trust relationship with that user
    (a bearer token belonging to that user). Otherwise the consent screen is
    required. This holds whether or not the user has reviewed their credentials:
    an unreviewed account is still a pre-existing account that a caller must not
    be able to silently link."""

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
        return self._post_api(ACCOUNT_REQUESTS_URL, {**data, "client_id": client_id})

    def _post_as_bearer_partner(self, data: dict, token: str):
        return self._post_with_bearer(ACCOUNT_REQUESTS_URL, data, token=token)

    def _account_request_payload(self, **overrides):
        payload = {
            "id": "acctreq_silent_test",
            "email": "existing@example.com",
            "scopes": ["query:read"],
            "code_challenge": VALID_CODE_CHALLENGE,
            "code_challenge_method": "S256",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
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
        attacker_token = self._make_live_access_token(attacker, self.bearer_partner).token

        res = self._post_as_bearer_partner(self._account_request_payload(), token=attacker_token)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        assert "oauth" not in data

    @parameterized.expand([("reviewed", True), ("unreviewed", False)])
    def test_bearer_caller_can_remint_for_own_user(self, _name, reviewed):
        # The legitimate bearer re-link path: the caller presents the user's own token, which
        # is genuine proof of an existing trust relationship, so it stays silent in either state.
        user = self._make_user(credentials_reviewed=reviewed)
        token = self._make_live_access_token(user, self.bearer_partner).token

        res = self._post_as_bearer_partner(self._account_request_payload(), token=token)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        assert "code" in data["oauth"]


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
