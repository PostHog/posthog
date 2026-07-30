from parameterized import parameterized

from ee.api.agentic_provisioning.test.base import ProvisioningTestBase

RESOURCE_ID = "res_placeholder"

PROVISIONING_ALIAS_URLS = [
    ("account_requests", "/api/provisioning/account_requests", "POST"),
    ("oauth_token", "/api/provisioning/oauth/token", "POST"),
    ("resources_create", "/api/provisioning/resources", "POST"),
    ("rotate_credentials", f"/api/provisioning/resources/{RESOURCE_ID}/rotate_credentials", "POST"),
    ("resource_remove", f"/api/provisioning/resources/{RESOURCE_ID}/remove", "POST"),
    ("resource_detail", f"/api/provisioning/resources/{RESOURCE_ID}", "GET"),
    ("deep_links", "/api/provisioning/deep_links", "POST"),
    ("github_grants_create", "/api/provisioning/github/grants", "POST"),
    ("github_integration", f"/api/provisioning/resources/{RESOURCE_ID}/github_integration", "POST"),
    ("wizard_runs", f"/api/provisioning/resources/{RESOURCE_ID}/wizard_runs", "POST"),
]


class TestProvisioningUrlAliases(ProvisioningTestBase):
    @parameterized.expand(PROVISIONING_ALIAS_URLS)
    def test_route_resolves(self, _name: str, url: str, method: str):
        if method == "GET":
            res = self._get_api(url)
        else:
            res = self._post_api(url)
        assert res.status_code != 404, f"{method} {url} returned 404 — route not registered"
