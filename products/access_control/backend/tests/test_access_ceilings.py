from posthog.test.base import APIBaseTest, BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.ceilings import MCP_USER_AGENT_MARKER, channel_ceiling
from products.access_control.backend.models import AccessCeiling


class TestChannelCeilingResolution(BaseTest):
    def test_resource_row_overrides_wildcard_row(self) -> None:
        AccessCeiling.objects.create(organization=self.organization, channel="mcp", resource=None, max_level="viewer")
        AccessCeiling.objects.create(
            organization=self.organization, channel="mcp", resource="feature_flag", max_level="editor"
        )

        assert channel_ceiling(self.organization, "mcp", "dashboard") == AccessCeiling.MaxLevel.VIEWER
        assert channel_ceiling(self.organization, "mcp", "feature_flag") == AccessCeiling.MaxLevel.EDITOR
        assert channel_ceiling(self.organization, "mcp") == AccessCeiling.MaxLevel.VIEWER

    def test_no_rows_and_no_channel_mean_unrestricted(self) -> None:
        assert channel_ceiling(self.organization, "mcp", "dashboard") is None
        assert channel_ceiling(self.organization, None, "dashboard") is None


class TestMCPReadOnlyEnforcement(APIBaseTest):
    """The regression these guard: a write-scoped token arriving through the MCP pathway must be
    denied when the org caps the channel, including `*`-scoped tokens, while reads and non-MCP
    requests stay untouched. No existing test exercises the ceiling path at all."""

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

    def _request(self, method: str, body: dict | None = None, mcp: bool = True):
        return getattr(self.client, method)(
            f"/api/projects/{self.team.id}/feature_flags/",
            body or {},
            HTTP_AUTHORIZATION=f"Bearer {self.key_value}",
            headers={"User-Agent": f"cursor/1.0 {MCP_USER_AGENT_MARKER}; version: 1.0.0"} if mcp else None,
        )

    def test_capped_channel_denies_writes_allows_reads(self) -> None:
        AccessCeiling.objects.create(organization=self.organization, channel="mcp", max_level="viewer")

        denied = self._request("post", {"key": "flag-via-mcp", "name": "flag"})
        assert denied.status_code == 403
        assert "read-only" in denied.json()["detail"]

        assert self._request("get").status_code == 200

    @parameterized.expand([("no_ceiling_row", True), ("not_mcp_user_agent", False)])
    def test_writes_pass_without_a_matching_ceiling(self, _name: str, mcp: bool) -> None:
        if not mcp:
            AccessCeiling.objects.create(organization=self.organization, channel="mcp", max_level="viewer")

        response = self._request("post", {"key": f"flag-{_name}", "name": "flag"}, mcp=mcp)
        assert response.status_code == 201

    def test_resource_exception_lets_that_resource_write(self) -> None:
        AccessCeiling.objects.create(organization=self.organization, channel="mcp", max_level="viewer")
        AccessCeiling.objects.create(
            organization=self.organization, channel="mcp", resource="feature_flag", max_level="editor"
        )

        response = self._request("post", {"key": "flag-excepted", "name": "flag"})
        assert response.status_code == 201
