from posthog.test.base import APIBaseTest

from django.http import HttpRequest
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.auth import (
    MCP_USER_AGENT_MARKER,
    IDJagAccessTokenAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    is_mcp_request,
)
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value


class TestMCPAccessSetting(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS,
                "name": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS,
            }
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_toggle_round_trip(self) -> None:
        response = self.client.patch("/api/organizations/@current/", {"read_only_mcp_access": True})
        assert response.status_code == 200
        assert response.json()["read_only_mcp_access"] is True
        self.organization.refresh_from_db()
        assert self.organization.read_only_mcp_access is True

        response = self.client.patch("/api/organizations/@current/", {"read_only_mcp_access": False})
        assert response.json()["read_only_mcp_access"] is False

    def test_toggle_requires_the_entitlement(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        response = self.client.patch("/api/organizations/@current/", {"read_only_mcp_access": True})
        assert response.status_code == 400
        assert response.json()["code"] == "payment_required"


class TestMCPReadOnlyEnforcement(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS,
                "name": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS,
            },
            # So the multi-project plan gate passes and MCPAccessPermission is the denier
            # on the root-create path, not PremiumMultiProjectPermission.
            {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": AvailableFeature.ORGANIZATIONS_PROJECTS},
        ]
        self.organization.save()
        # Owner, not the default member: the cap binds every level, so the membership
        # permissions must pass for MCPAccessPermission to be the one that denies.
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        self.key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="mcp test",
            user=self.user,
            secure_value=hash_key_value(self.key_value),
            scopes=["*"],
        )
        self.client.logout()

    def _set_read_only(self, value: bool) -> None:
        self.organization.read_only_mcp_access = value
        self.organization.save()

    def _request(self, method: str, body: dict | None = None, mcp: bool = True):
        return getattr(self.client, method)(
            f"/api/projects/{self.team.id}/feature_flags/",
            body or {},
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
            headers={"User-Agent": f"cursor/1.0 {MCP_USER_AGENT_MARKER}; version: 1.0.0"} if mcp else None,
        )

    def test_read_only_org_denies_mcp_writes_and_allows_reads(self) -> None:
        self._set_read_only(True)

        denied = self._request("post", {"key": "mcp-e2e-should-fail", "name": "e2e"})
        assert denied.status_code == 403
        assert "read-only" in denied.json()["detail"]

        assert self._request("get").status_code == 200

    @parameterized.expand([("flag_off", False, True), ("not_mcp_user_agent", True, False)])
    def test_writes_pass_without_flag_or_marker(self, _name: str, read_only: bool, mcp: bool) -> None:
        self._set_read_only(read_only)

        response = self._request("post", {"key": f"flag-{_name}", "name": "e2e"}, mcp=mcp)
        assert response.status_code == 201

    def test_root_create_is_capped_against_the_current_org(self) -> None:
        # A create has no object to defer to; it lands in the caller's current org, which
        # here is the read-only one. POST /api/projects/ must be capped.
        self._set_read_only(True)

        response = self.client.post(
            "/api/projects/",
            {"name": "new project via mcp"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
            headers={"User-Agent": f"cursor/1.0 {MCP_USER_AGENT_MARKER}; version: 1.0.0"},
        )
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]

    def test_root_viewset_caps_against_the_target_org_not_current_org(self) -> None:
        # The read-only org is the target; the caller's *current* org is a different,
        # uncapped one. A root environment write must be capped against the target.
        from posthog.models.organization import Organization

        self._set_read_only(True)
        other_org, _, _ = Organization.objects.bootstrap(self.user, name="uncapped current org")
        self.user.current_organization = other_org
        self.user.save()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/",
            {"name": "renamed via mcp"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
            headers={"User-Agent": f"cursor/1.0 {MCP_USER_AGENT_MARKER}; version: 1.0.0"},
        )
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]

    def test_dangerously_defined_permission_chains_are_still_capped(self) -> None:
        self._set_read_only(True)

        response = self.client.patch(
            "/api/organizations/@current/",
            {"name": "renamed via mcp"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
            headers={"User-Agent": f"cursor/1.0 {MCP_USER_AGENT_MARKER}; version: 1.0.0"},
        )
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]

    def test_non_member_gets_the_generic_denial_not_the_policy_message(self) -> None:
        from posthog.models.organization import Organization

        self._set_read_only(True)
        _, _, other_team = Organization.objects.bootstrap(None, name="other org")

        response = self.client.post(
            f"/api/projects/{other_team.id}/feature_flags/",
            {"key": "cross-org-probe", "name": "probe"},
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
            headers={"User-Agent": f"cursor/1.0 {MCP_USER_AGENT_MARKER}; version: 1.0.0"},
        )
        assert response.status_code == 403
        assert "read-only" not in response.json()["detail"]

    def test_flag_without_entitlement_does_not_enforce(self) -> None:
        self._set_read_only(True)
        self.organization.available_product_features = []
        self.organization.save()

        assert self._request("post", {"key": "flag-unentitled", "name": "e2e"}).status_code == 201


class TestIsMCPRequest(SimpleTestCase):
    @staticmethod
    def _request(authenticator: object, user_agent: str) -> HttpRequest:
        request = HttpRequest()
        request.META["HTTP_USER_AGENT"] = user_agent
        request.successful_authenticator = authenticator  # type: ignore[attr-defined]
        return request

    @parameterized.expand(
        [
            ("personal_api_key", PersonalAPIKeyAuthentication),
            ("oauth", OAuthAccessTokenAuthentication),
            ("id_jag", IDJagAccessTokenAuthentication),
        ]
    )
    def test_scoped_token_with_mcp_user_agent_is_mcp(self, _name: str, auth_class: type) -> None:
        assert is_mcp_request(self._request(auth_class(), f"cursor/1.0 {MCP_USER_AGENT_MARKER}")) is True

    def test_scoped_token_without_mcp_user_agent_is_not_mcp(self) -> None:
        assert is_mcp_request(self._request(PersonalAPIKeyAuthentication(), "curl/8")) is False

    def test_session_auth_is_never_mcp(self) -> None:
        assert is_mcp_request(self._request(SessionAuthentication(), MCP_USER_AGENT_MARKER)) is False
