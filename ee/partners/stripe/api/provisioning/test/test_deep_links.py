from urllib.parse import parse_qs, urlparse

from parameterized import parameterized

from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

DEEP_LINKS_URL = f"{BASE_PATH}/provisioning/deep_links"


class TestDeepLinks(StripeProvisioningTestBase):
    def test_deep_link_logs_the_user_in_via_agentic_login(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            DEEP_LINKS_URL, data={"purpose": "dashboard", "path": f"/project/{self.team.id}/insights"}, token=token
        )
        assert res.status_code == 200
        body = res.json()
        assert body["purpose"] == "dashboard"
        assert body["expires_at"]
        assert f"team_id={self.team.id}" in body["url"]
        assert "/api/partners/stripe/login?token=" in body["url"]

        self.user.is_email_verified = True
        self.user.save(update_fields=["is_email_verified"])
        self.client.logout()

        deep_link_token = parse_qs(urlparse(body["url"]).query)["token"][0]
        login = self.client.get(f"/api/partners/stripe/login?token={deep_link_token}")
        assert login.status_code == 302
        assert login["Location"] == f"/project/{self.team.id}/insights"

        me = self.client.get("/api/users/@me/")
        assert me.status_code == 200
        assert me.json()["email"] == self.user.email

    @parameterized.expand(
        [
            ("absolute_url", "https://evil.example.com/phish"),
            ("protocol_relative", "//evil.example.com"),
            ("backslash_host", "/\\evil.example.com"),
        ]
    )
    def test_unsafe_paths_rejected(self, _name, path):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(DEEP_LINKS_URL, data={"path": path}, token=token)
        assert res.status_code == 400
        assert res.json()["error"] == {
            "code": "invalid_path",
            "message": "path must be a relative in-app path beginning with a single '/'",
        }
