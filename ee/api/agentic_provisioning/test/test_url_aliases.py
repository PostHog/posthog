from parameterized import parameterized

from ee.api.agentic_provisioning.test.base import ProvisioningTestBase

RESOURCE_ID = "res_placeholder"

PROVISIONING_ALIAS_URLS = [
    ("health", "/api/provisioning/health", "GET"),
    ("services", "/api/provisioning/services", "GET"),
    ("account_requests", "/api/provisioning/account_requests", "POST"),
    ("oauth_token", "/api/provisioning/oauth/token", "POST"),
    ("resources_create", "/api/provisioning/resources", "POST"),
    ("rotate_credentials", f"/api/provisioning/resources/{RESOURCE_ID}/rotate_credentials", "POST"),
    ("update_service", f"/api/provisioning/resources/{RESOURCE_ID}/update_service", "POST"),
    ("resource_remove", f"/api/provisioning/resources/{RESOURCE_ID}/remove", "POST"),
    ("resource_detail", f"/api/provisioning/resources/{RESOURCE_ID}", "GET"),
    ("deep_links", "/api/provisioning/deep_links", "POST"),
]


class TestProvisioningUrlAliases(ProvisioningTestBase):
    @parameterized.expand(PROVISIONING_ALIAS_URLS)
    def test_route_resolves(self, _name: str, url: str, method: str):
        if method == "GET":
            res = self._get_signed(url)
        else:
            res = self._post_signed(url)
        assert res.status_code != 404, f"{method} {url} returned 404 — route not registered"
