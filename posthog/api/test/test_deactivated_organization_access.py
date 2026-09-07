from posthog.test.base import APIBaseTest

from loginas import settings as la_settings
from parameterized import parameterized

from posthog.auth import MCP_USER_AGENT_MARKER
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.cdp.backend.models.plugin import Plugin

UNPAID = "Access revoked due to unpaid balance."


class TestDeactivatedOrganizationAPIAccess(APIBaseTest):
    """An organization whose access was revoked keeps its session pathway into the app, which the
    revocation screens and the billing flow that reactivates it need. Every token pathway is
    closed, the MCP server included."""

    def setUp(self) -> None:
        super().setUp()
        # Owner, not the default member: the check binds every level, so the membership
        # permissions must pass for ActiveOrganizationPermission to be the one that denies.
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        self.key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="deactivation test",
            user=self.user,
            secure_value=hash_key_value(self.key_value),
            scopes=["*"],
        )
        self.client.logout()

    def _deactivate(self, reason: str = UNPAID) -> None:
        self.organization.is_active = False
        self.organization.is_not_active_reason = reason
        self.organization.save()

    def _token_request(self, method: str, path: str, body: dict | None = None, mcp: bool = False):
        return getattr(self.client, method)(
            path,
            body or {},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
            headers={"User-Agent": f"cursor/1.0 {MCP_USER_AGENT_MARKER}; version: 1.0.0"} if mcp else None,
        )

    def _flags_path(self, team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/feature_flags/"

    def test_active_organization_allows_token_access(self) -> None:
        assert self._token_request("get", self._flags_path()).status_code == 200

    def test_deactivated_organization_denies_token_reads_with_the_operator_reason(self) -> None:
        self._deactivate()

        response = self._token_request("get", self._flags_path())

        assert response.status_code == 403
        assert response.json()["detail"] == f"Your organization has been deactivated. {UNPAID}"

    def test_deactivated_organization_denies_token_writes(self) -> None:
        self._deactivate()

        response = self._token_request("post", self._flags_path(), {"key": "should-fail", "name": "probe"})

        assert response.status_code == 403
        assert "deactivated" in response.json()["detail"]

    def test_pending_deletion_organization_denies_token_access(self) -> None:
        self.organization.is_pending_deletion = True
        self.organization.save()

        response = self._token_request("get", self._flags_path())

        assert response.status_code == 403
        assert response.json()["detail"] == "Your organization is being deleted."

    def test_deactivated_organization_denies_mcp_requests(self) -> None:
        self._deactivate()

        response = self._token_request("get", self._flags_path(), mcp=True)

        assert response.status_code == 403
        assert "deactivated" in response.json()["detail"]

    def test_denial_without_a_reason_carries_the_generic_message(self) -> None:
        self._deactivate(reason="")

        response = self._token_request("get", self._flags_path())

        assert response.json()["detail"] == "Your organization has been deactivated."

    def test_root_viewset_object_target_is_capped(self) -> None:
        # /api/environments/<id>/ names no parent in the URL, so the target organization comes
        # from the fetched object in has_object_permission.
        self._deactivate()

        response = self._token_request("patch", f"/api/environments/{self.team.id}/", {"name": "renamed"})

        assert response.status_code == 403
        assert "deactivated" in response.json()["detail"]

    def test_session_auth_is_denied_too(self) -> None:
        self._deactivate()
        self.client.force_login(self.user)

        response = self.client.get(self._flags_path())

        assert response.status_code == 403
        assert response.json()["detail"] == f"Your organization has been deactivated. {UNPAID}"

    @parameterized.expand(
        [
            ("the caller's own profile", "/api/users/@me/"),
            ("the organization behind the revocation screen", "/api/organizations/@current/"),
            ("billing, so the balance can be paid", "/api/billing/period/"),
        ]
    )
    def test_the_reactivation_path_stays_reachable_on_a_session(self, _name, path) -> None:
        # The app's revocation screens and its payment flow run on a session, so these three reads
        # are the boundary's whole exemption. A regression here locks a paying customer out of the
        # flow that lifts the deactivation.
        self._deactivate()
        self.client.force_login(self.user)

        assert self.client.get(path).status_code == 200

    def test_a_revoked_organization_cannot_write_to_itself(self) -> None:
        # The organization is exempt for reads only, so the screen can name the reason while a
        # revoked organization still cannot change its own settings.
        self._deactivate()
        self.client.force_login(self.user)

        response = self.client.patch(
            "/api/organizations/@current/", {"name": "renamed"}, content_type="application/json"
        )

        assert response.status_code == 403
        assert "deactivated" in response.json()["detail"]

    def test_staff_impersonation_still_reaches_a_revoked_organization(self) -> None:
        # Support has to investigate the organizations that were revoked, and starting an
        # impersonation session already needs staff access.
        self._deactivate()
        self.client.force_login(self.user)
        session = self.client.session
        session[la_settings.USER_SESSION_FLAG] = str(self.user.pk)
        session.save()

        assert self.client.get(self._flags_path()).status_code == 200

    def test_user_endpoint_stays_reachable(self) -> None:
        self._deactivate()

        assert self._token_request("get", "/api/users/@me/").status_code == 200

    def test_billing_stays_reachable_so_the_organization_can_pay(self) -> None:
        self._deactivate()

        assert self._token_request("get", "/api/billing/period/").status_code == 200

    def test_a_healthy_target_organization_is_not_denied(self) -> None:
        self._deactivate()
        _, _, healthy_team = Organization.objects.bootstrap(self.user, name="healthy org")
        self.user.current_organization = healthy_team.organization
        self.user.save()

        assert self._token_request("get", self._flags_path(healthy_team.id)).status_code == 200

    def test_another_organizations_revocation_is_not_observable_to_a_non_member(self) -> None:
        # This gate caps a revoked organization's own usage, so a caller from outside it must get
        # the same answer either way. The plugin viewset omits the membership permission so global
        # plugins stay readable across organizations, which is what would make a denial here both
        # observable and a break of that cross-organization read.
        victim = Organization.objects.create(name="victim org")
        plugin = Plugin.objects.create(organization=victim, name="global plugin", is_global=True)
        path = f"/api/organizations/{victim.id}/plugins/{plugin.id}/"

        healthy = self._token_request("get", path)

        victim.is_active = False
        victim.is_not_active_reason = UNPAID
        victim.save()
        revoked = self._token_request("get", path)

        assert revoked.status_code == healthy.status_code
        assert UNPAID not in revoked.content.decode()

    def test_reactivation_restores_token_access(self) -> None:
        self._deactivate()
        self.organization.is_active = True
        self.organization.save()

        assert self._token_request("get", self._flags_path()).status_code == 200
