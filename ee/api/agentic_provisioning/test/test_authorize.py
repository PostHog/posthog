from urllib.parse import quote

from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.oauth import OAuthApplication
from posthog.models.user import User

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX
from ee.api.agentic_provisioning.test.base import TEST_PARTNER_SCOPES, ProvisioningTestBase

PARTNER_CALLBACK = "https://partner.example.com/callback"


class AuthorizeTestBase(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def _set_pending_auth(self, state: str, email: str, partner: OAuthApplication | None = None, **extra):
        partner = partner or self.partner
        data = {
            "email": email,
            "scopes": ["query:read", "project:read"],
            "partner_id": str(partner.id),
            "partner_name": partner.name,
            "region": "US",
            **extra,
        }
        cache.set(f"{PENDING_AUTH_CACHE_PREFIX}{state}", data, timeout=600)

    def _make_skip_consent_partner(self) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id="authorize-skip-consent-partner",
            name="Skip Consent Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=PARTNER_CALLBACK,
            algorithm="RS256",
            is_first_party=True,
            scopes=TEST_PARTNER_SCOPES,
            provisioning_auth_method="bearer",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_skip_existing_user_consent=True,
        )


class TestAgenticAuthorize(AuthorizeTestBase):
    def test_requires_login(self):
        self.client.logout()
        res = self.client.get("/api/agentic/authorize?state=test_state")
        assert res.status_code == 302
        assert "/login" in res["Location"]

    def test_expired_state_redirects_with_error(self):
        res = self.client.get("/api/agentic/authorize?state=nonexistent")
        assert res.status_code == 302
        assert "error=expired_or_invalid_state" in res["Location"]

    def test_missing_state_redirects_with_error(self):
        res = self.client.get("/api/agentic/authorize")
        assert res.status_code == 302
        assert "error=missing_state" in res["Location"]

    def test_email_mismatch_redirects_to_mismatch_page(self):
        self._set_pending_auth("state_mismatch", "other@example.com", partner_name="Test Partner")
        res = self.client.get("/api/agentic/authorize?state=state_mismatch")
        assert res.status_code == 302
        assert "/agentic/account-mismatch" in res["Location"]
        assert "expected_email=other%40example.com" in res["Location"]
        assert f"current_email={quote(self.user.email)}" in res["Location"]
        assert "partner_name=Test+Partner" in res["Location"]
        assert "state=state_mismatch" in res["Location"]

    def test_trusted_partner_auto_redirects_with_code(self):
        partner = self._make_skip_consent_partner()
        self._set_pending_auth("state_ok", self.user.email, partner=partner, consent_required=False)
        res = self.client.get("/api/agentic/authorize?state=state_ok")
        assert res.status_code == 302
        assert res["Location"].startswith(PARTNER_CALLBACK)
        assert "code=" in res["Location"]
        assert "state=state_ok" in res["Location"]

        code = res["Location"].split("code=")[1].split("&")[0]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data is not None
        assert code_data["user_id"] == self.user.id
        assert code_data["org_id"] == str(self.team.organization.id)
        assert code_data["team_id"] == self.team.id
        assert code_data["scopes"] == ["query:read", "project:read"]
        assert code_data["partner_id"] == str(partner.id)
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_ok") is None

    @parameterized.expand(
        [
            # consent_required=True forces the consent UI for a skip-consent partner whose request
            # fell through to consent (trust not proven), even for a single-org/single-team user.
            ("consent_required_flag_set", {"consent_required": True}),
            # Fail closed: a partner-identified pending state missing the flag (e.g. cached by an
            # older pod mid-deploy) must not auto-approve either.
            ("flag_missing_fails_closed", {}),
        ]
    )
    def test_skip_consent_partner_not_auto_approved(self, name, extra):
        partner = self._make_skip_consent_partner()
        state = f"state_{name}"
        self._set_pending_auth(state, self.user.email, partner=partner, **extra)
        res = self.client.get(f"/api/agentic/authorize?state={state}")
        assert res.status_code == 302
        assert "/agentic/authorize?" in res["Location"]
        assert not res["Location"].startswith(PARTNER_CALLBACK)
        assert "code=" not in res["Location"]
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}{state}") is not None

    def test_pending_state_without_partner_not_auto_trusted(self):
        self._set_pending_auth("state_no_partner", self.user.email, partner_id="", partner_name="")
        res = self.client.get("/api/agentic/authorize?state=state_no_partner")
        assert res.status_code == 302
        assert "/agentic/authorize?" in res["Location"]
        assert "code=" not in res["Location"]
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_no_partner") is not None

    def test_user_without_org_redirects_with_error(self):
        orphan = User.objects.create(email="orphan@example.com", first_name="Orphan")
        self.client.force_login(orphan)
        self._set_pending_auth("state_no_org", "orphan@example.com", scopes=[])
        res = self.client.get("/api/agentic/authorize?state=state_no_org")
        assert res.status_code == 302
        assert "error=no_organization" in res["Location"]

    def test_full_authorize_flow_with_token_exchange(self):
        partner = self._make_skip_consent_partner()
        verifier, challenge = self._pkce_pair()
        self._set_pending_auth(
            "state_e2e",
            self.user.email,
            partner=partner,
            consent_required=False,
            code_challenge=challenge,
            code_challenge_method="S256",
        )

        res = self.client.get("/api/agentic/authorize?state=state_e2e")
        assert res.status_code == 302
        code = res["Location"].split("code=")[1].split("&")[0]

        token_res = self._post_api(
            "/api/agentic/oauth/token",
            {"grant_type": "authorization_code", "code": code, "code_verifier": verifier},
        )
        assert token_res.status_code == 200
        data = token_res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"


class AgenticAuthorizeMultiOrgBase(AuthorizeTestBase):
    def setUp(self):
        super().setUp()
        self.org2 = Organization.objects.create(name="Second Org")
        OrganizationMembership.objects.create(user=self.user, organization=self.org2, level=15)
        self.team2 = Team.objects.create(organization=self.org2, name="Second Project", api_token="token_2")


class TestAgenticAuthorizeMultiOrg(AgenticAuthorizeMultiOrgBase):
    def test_multi_org_redirects_to_spa(self):
        self._set_pending_auth("state_multi", self.user.email)
        res = self.client.get("/api/agentic/authorize?state=state_multi&scope=query:read+project:read")
        assert res.status_code == 302
        assert "/agentic/authorize?" in res["Location"]
        assert "state=state_multi" in res["Location"]

    def test_multi_org_does_not_consume_state(self):
        self._set_pending_auth("state_preserve", self.user.email)
        self.client.get("/api/agentic/authorize?state=state_preserve")
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_preserve") is not None


class TestAgenticAuthorizeConfirm(AgenticAuthorizeMultiOrgBase):
    def _confirm(self, state: str, team_id):
        return self._post_api("/api/agentic/authorize/confirm/", {"state": state, "team_id": team_id})

    def test_confirm_creates_auth_code_for_selected_team(self):
        self._set_pending_auth("state_confirm", self.user.email)
        res = self._confirm("state_confirm", self.team2.id)
        assert res.status_code == 200
        data = res.json()
        assert data["redirect_url"].startswith(PARTNER_CALLBACK)
        assert "code=" in data["redirect_url"]
        assert "state=state_confirm" in data["redirect_url"]

        code = data["redirect_url"].split("code=")[1].split("&")[0]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data["team_id"] == self.team2.id
        assert code_data["org_id"] == str(self.org2.id)

    def test_confirm_consumes_pending_state(self):
        self._set_pending_auth("state_consume", self.user.email)
        self._confirm("state_consume", self.team.id)
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_consume") is None

    @patch("ee.api.agentic_provisioning.views._capture_provisioning_event")
    def test_confirm_success_attributes_partner(self, mock_capture_event):
        partner = OAuthApplication.objects.create(
            client_id="confirm-attribution-partner",
            name="Confirm Attribution Client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=PARTNER_CALLBACK,
            algorithm="RS256",
            provisioning_auth_method="pkce",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
        )
        self._set_pending_auth("state_attr", self.user.email, partner=partner)
        res = self._confirm("state_attr", self.team.id)
        assert res.status_code == 200

        success_calls = [
            call for call in mock_capture_event.call_args_list if call.args[:2] == ("authorize_confirm", "success")
        ]
        assert len(success_calls) == 1
        assert success_calls[0].kwargs["partner"] == partner

    def test_confirm_without_partner_returns_missing_callback(self):
        self._set_pending_auth("state_no_partner", self.user.email, partner_id="")
        res = self._confirm("state_no_partner", self.team.id)
        assert res.status_code == 400
        assert res.json()["error"] == "missing_callback"

    def test_confirm_rejects_expired_state(self):
        res = self._confirm("nonexistent", self.team.id)
        assert res.status_code == 400
        assert res.json()["error"] == "expired_or_invalid_state"

    def test_confirm_rejects_email_mismatch(self):
        self._set_pending_auth("state_wrong_email", "other@example.com")
        res = self._confirm("state_wrong_email", self.team.id)
        assert res.status_code == 403
        assert res.json()["error"] == "email_mismatch"

    def test_confirm_rejects_inaccessible_team(self):
        self._set_pending_auth("state_no_access", self.user.email)
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Project", api_token="token_other")

        res = self._confirm("state_no_access", other_team.id)
        assert res.status_code == 403
        assert res.json()["error"] == "team_not_accessible"

    def test_confirm_rejects_nonexistent_team(self):
        self._set_pending_auth("state_bad_team", self.user.email)
        res = self._confirm("state_bad_team", 999999)
        assert res.status_code == 404
        assert res.json()["error"] == "team_not_found"

    def test_confirm_rejects_missing_params(self):
        res = self._post_api("/api/agentic/authorize/confirm/", {"state": "something"})
        assert res.status_code == 400
