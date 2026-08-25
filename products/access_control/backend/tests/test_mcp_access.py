from posthog.test.base import APIBaseTest

from django.http import HttpResponse

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.mcp_access import MCP_USER_AGENT_MARKER


class TestMCPReadOnlyEnforcement(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS,
                "name": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS,
            }
        ]
        self.organization.save()
        self.key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="mcp test",
            user=self.user,
            secure_value=hash_key_value(self.key_value),
            scopes=["*"],
        )
        self.client.logout()

    def _set_read_only(self, value: bool) -> None:
        self.organization.mcp_access_read_only = value
        self.organization.save()

    def _request(self, method: str, body: dict | None = None, mcp: bool = True) -> HttpResponse:
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

    def test_flag_without_entitlement_does_not_enforce(self) -> None:
        self._set_read_only(True)
        self.organization.available_product_features = []
        self.organization.save()

        assert self._request("post", {"key": "flag-unentitled", "name": "e2e"}).status_code == 201
