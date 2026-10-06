from urllib.parse import quote

from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.oauth import OAuthApplication
from posthog.models.organization_provisioning import get_billing_lock_partner
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User

from ee.api.agentic_provisioning.constants import AUTH_CODE_CACHE_PREFIX, PENDING_AUTH_CACHE_PREFIX
from ee.api.agentic_provisioning.test.base import (
    TEST_PARTNER_CLIENT_SECRET,
    TEST_PARTNER_SCOPES,
    ProvisioningTestBase,
    provisioning_config,
)

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
            client_secret=TEST_PARTNER_CLIENT_SECRET,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=PARTNER_CALLBACK,
            algorithm="RS256",
            is_first_party=True,
            scopes=TEST_PARTNER_SCOPES,
            is_provisioning_partner=True,
            _provisioning_config=provisioning_config(active=True, skip_existing_user_consent=True),
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

    def test_trusted_partner_auto_redirect_skips_restricted_team(self):
        partner = self._make_skip_consent_partner()
        self._restrict_team_access(self.team)
        self._set_pending_auth("state_restricted", self.user.email, partner=partner, consent_required=False)

        res = self.client.get("/api/agentic/authorize?state=state_restricted")

        assert res.status_code == 302
        assert res["Location"].startswith(PARTNER_CALLBACK)
        code = res["Location"].split("code=")[1].split("&")[0]
        code_data = cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")
        assert code_data["team_id"] != self.team.id

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

    def test_paying_partner_goes_to_consent_without_touching_the_users_projects(self) -> None:
        partner = self._make_skip_consent_partner()
        partner.update_provisioning(pays_for_customers=True)
        self._restrict_team_access(self.team)
        self._set_pending_auth("state_paying", self.user.email, partner=partner, consent_required=False)
        team_count = Team.objects.count()

        res = self.client.get("/api/agentic/authorize?state=state_paying")

        assert res.status_code == 302
        assert res["Location"].endswith("/agentic/authorize?state=state_paying")
        assert Team.objects.count() == team_count

    def test_pending_state_without_partner_not_auto_trusted(self):
        self._set_pending_auth("state_no_partner", self.user.email, partner_id="", partner_name="")
        res = self.client.get("/api/agentic/authorize?state=state_no_partner")
        assert res.status_code == 302
        assert "/agentic/authorize?" in res["Location"]
        assert "code=" not in res["Location"]
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_no_partner") is not None

    @parameterized.expand(
        [
            ("partner_that_does_not_pay", False, "?error=no_organization"),
            ("partner_that_pays_creates_the_organization_on_confirm", True, "/agentic/authorize?state=state_no_org"),
        ]
    )
    def test_user_without_org(self, _name: str, partner_pays: bool, expected_location_end: str) -> None:
        self.partner.update_provisioning(pays_for_customers=partner_pays)
        orphan = User.objects.create(email="orphan@example.com", first_name="Orphan")
        self.client.force_login(orphan)
        self._set_pending_auth("state_no_org", "orphan@example.com", scopes=[])
        res = self.client.get("/api/agentic/authorize?state=state_no_org")
        assert res.status_code == 302
        assert res["Location"].endswith(expected_location_end)

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
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                **self._client_credentials(partner),
            },
        )
        assert token_res.status_code == 200
        data = token_res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"


class TestAgenticAuthorizePending(AuthorizeTestBase):
    def _pending(self, state: str) -> dict:
        return self.client.get(f"/api/agentic/authorize/pending/?state={state}").json()

    def test_reports_whether_the_partner_pays_and_the_organization_it_already_has(self) -> None:
        self._set_pending_auth("state_unpaid", self.user.email)
        unpaid = self._pending("state_unpaid")

        self.partner.update_provisioning(pays_for_customers=True)
        self._set_pending_auth("state_first", self.user.email)
        first = self._pending("state_first")
        self._post_api("/api/agentic/authorize/confirm/", {"state": "state_first"})
        self._set_pending_auth("state_again", self.user.email)
        again = self._pending("state_again")

        assert [(body["pays_for_customers"], body["partner_organization_name"]) for body in (unpaid, first, again)] == [
            (False, None),
            (True, None),
            (True, f"{self.partner.name} ({self.user.email})"),
        ]


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
        self.org2.refresh_from_db()
        assert (self.org2.provisioning_source, self.org2.provisioning_application_id) == (None, None)

    def _code_data(self, res) -> dict:
        code = res.json()["redirect_url"].split("code=")[1].split("&")[0]
        return cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}")

    def test_paying_partner_confirm_puts_the_project_in_a_new_organization_the_partner_pays_for(self) -> None:
        self.partner.update_provisioning(pays_for_customers=True)
        # Long enough that the app name plus the email overflows Organization.name.
        self.user.email = "a.long.mailbox.name.for.this.test@example.com"
        self.user.save()
        self._set_pending_auth("state_paying", self.user.email)

        res = self._confirm("state_paying", self.team.id)

        assert res.status_code == 200
        code_data = self._code_data(res)
        team = Team.objects.select_related("organization").get(id=code_data["team_id"])
        organization = team.organization
        assert code_data["org_id"] == str(organization.id)
        assert organization.id not in (self.organization.id, self.org2.id)
        assert organization.name == f"{self.partner.name} ({self.user.email})"[:64]
        assert organization.memberships.get(user=self.user).level == OrganizationMembership.Level.OWNER
        assert (organization.provisioning_source, organization.provisioning_application_id) == (
            Organization.ProvisioningSource.PROVISIONING_API,
            self.partner.id,
        )
        assert get_billing_lock_partner(organization) == self.partner
        assert TeamProvisioningConfig.objects.get(team=team).application == self.partner
        self.user.refresh_from_db()
        assert (self.user.current_organization_id, self.user.current_team_id) == (self.organization.id, self.team.id)

    def test_paying_partner_confirm_reuses_the_organization_the_partner_already_provisioned(self) -> None:
        self.partner.update_provisioning(pays_for_customers=True)
        organization = Organization.objects.create(
            name="Partner-created organization",
            provisioning_source=Organization.ProvisioningSource.PROVISIONING_API,
            provisioning_application=self.partner,
        )
        OrganizationMembership.objects.create(
            user=self.user, organization=organization, level=OrganizationMembership.Level.OWNER
        )
        team = Team.objects.create_with_data(initiating_user=self.user, organization=organization)
        TeamProvisioningConfig.objects.create(team=team, application=self.partner)
        organization_count = Organization.objects.count()

        self._set_pending_auth("state_again", self.user.email)
        again = self._confirm("state_again", self.team2.id)

        assert self._code_data(again)["team_id"] == team.id
        assert Organization.objects.count() == organization_count

    @parameterized.expand(
        [
            ("now_pays_for_itself", {"customer_id": "cus_example"}, OrganizationMembership.Level.OWNER),
            ("pending_deletion", {"is_pending_deletion": True}, OrganizationMembership.Level.OWNER),
            ("deactivated", {"is_active": False}, OrganizationMembership.Level.OWNER),
            ("user_is_only_an_admin", {}, OrganizationMembership.Level.ADMIN),
        ]
    )
    def test_paying_partner_confirm_creates_a_new_organization_instead_of_reusing_one(
        self, _name: str, organization_changes: dict[str, object], membership_level: OrganizationMembership.Level
    ) -> None:
        self.partner.update_provisioning(pays_for_customers=True)
        self._set_pending_auth("state_first", self.user.email)
        first_organization_id = self._code_data(self._confirm("state_first", self.team.id))["org_id"]
        Organization.objects.filter(id=first_organization_id).update(**organization_changes)
        OrganizationMembership.objects.filter(user=self.user, organization_id=first_organization_id).update(
            level=membership_level
        )

        self._set_pending_auth("state_again", self.user.email)
        team = Team.objects.select_related("organization").get(
            id=self._code_data(self._confirm("state_again", self.team2.id))["team_id"]
        )

        assert str(team.organization_id) != first_organization_id
        assert get_billing_lock_partner(team.organization) == self.partner

    def test_paying_partner_confirm_never_reuses_a_project_the_partner_did_not_provision(self) -> None:
        self.partner.update_provisioning(pays_for_customers=True)
        self._set_pending_auth("state_first", self.user.email)
        partner_team = Team.objects.get(id=self._code_data(self._confirm("state_first", self.team.id))["team_id"])
        users_team = Team.objects.create_with_data(initiating_user=self.user, organization=partner_team.organization)
        # What removing the partner's project link (ResourceRemoveView) leaves behind.
        TeamProvisioningConfig.objects.filter(team=partner_team).delete()
        organization_count = Organization.objects.count()

        self._set_pending_auth("state_again", self.user.email)
        again = self._confirm("state_again", self.team2.id)

        team = Team.objects.select_related("organization").get(id=self._code_data(again)["team_id"])
        assert team.id not in (partner_team.id, users_team.id)
        assert (team.organization_id, Organization.objects.count()) == (
            partner_team.organization_id,
            organization_count,
        )
        assert get_billing_lock_partner(team.organization) == self.partner
        assert TeamProvisioningConfig.objects.get(team=team).application == self.partner

    def test_confirm_consumes_pending_state(self):
        self._set_pending_auth("state_consume", self.user.email)
        self._confirm("state_consume", self.team.id)
        assert cache.get(f"{PENDING_AUTH_CACHE_PREFIX}state_consume") is None

    @patch("ee.api.agentic_provisioning.views.authorize.capture_provisioning_event")
    def test_confirm_success_attributes_partner(self, mock_capture_event):
        partner = OAuthApplication.objects.create(
            client_id="confirm-attribution-partner",
            name="Confirm Attribution Client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=PARTNER_CALLBACK,
            algorithm="RS256",
            is_provisioning_partner=True,
            _provisioning_config=provisioning_config(active=True),
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

    @parameterized.expand(
        [
            ("with_team_id", True),
            # A paying partner's consent page sends no team_id, so an expired state must still read as expired.
            ("without_team_id", False),
        ]
    )
    def test_confirm_rejects_expired_state(self, _name: str, send_team_id: bool) -> None:
        body: dict[str, object] = {"state": "nonexistent"}
        if send_team_id:
            body["team_id"] = self.team.id
        res = self._post_api("/api/agentic/authorize/confirm/", body)
        assert res.status_code == 400
        assert res.json()["error"] == "expired_or_invalid_state"

    def test_confirm_rejects_email_mismatch(self):
        self._set_pending_auth("state_wrong_email", "other@example.com")
        res = self._confirm("state_wrong_email", self.team.id)
        assert res.status_code == 403
        assert res.json()["error"] == "email_mismatch"

    @parameterized.expand(["other_org", "restricted_in_own_org"])
    def test_confirm_rejects_inaccessible_team(self, case):
        self._set_pending_auth("state_no_access", self.user.email)
        if case == "other_org":
            other_org = Organization.objects.create(name="Other Org")
            target = Team.objects.create(organization=other_org, name="Other Project", api_token="token_other")
        else:
            target = Team.objects.create_with_data(
                initiating_user=self.user, organization=self.organization, name="Restricted project"
            )
            self._restrict_team_access(target)

        res = self._confirm("state_no_access", target.id)
        assert res.status_code == 403
        assert res.json()["error"] == "team_not_accessible"

    def test_confirm_rejects_nonexistent_team(self):
        self._set_pending_auth("state_bad_team", self.user.email)
        res = self._confirm("state_bad_team", 999999)
        assert res.status_code == 404
        assert res.json()["error"] == "team_not_found"

    def test_confirm_rejects_missing_params(self):
        self._set_pending_auth("state_without_team", self.user.email)
        res = self._post_api("/api/agentic/authorize/confirm/", {"state": "state_without_team"})
        assert res.status_code == 400
        assert res.json()["error"] == "state and team_id are required"
