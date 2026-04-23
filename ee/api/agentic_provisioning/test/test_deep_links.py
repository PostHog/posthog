from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase
from ee.api.agentic_provisioning.views import DEEP_LINK_CACHE_PREFIX


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestDeepLinks(StripeProvisioningTestBase):
    def test_deep_link_returns_url(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"purpose": "dashboard"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["purpose"] == "dashboard"
        assert "url" in data
        assert "expires_at" in data
        assert "token=" in data["url"]

    def test_deep_link_url_contains_team_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"purpose": "dashboard"},
            token=token,
        )
        url = res.json()["url"]
        assert f"team_id={self.team.id}" in url

    def test_deep_link_missing_bearer_returns_401(self):
        res = self._post_signed("/api/agentic/provisioning/deep_links", data={"purpose": "dashboard"})
        assert res.status_code == 401


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestAgenticLogin(StripeProvisioningTestBase):
    def _create_deep_link_token(self) -> str:
        token = "test_deep_link_token"
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": self.user.id, "team_id": self.team.id},
            timeout=600,
        )
        return token

    def test_valid_token_logs_in_and_redirects_to_project(self):
        token = self._create_deep_link_token()
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert res["Location"] == f"/project/{self.team.id}"

    def test_valid_token_creates_session(self):
        token = self._create_deep_link_token()
        self.client.get(f"/agentic/login?token={token}")
        res = self.client.get("/api/users/@me/")
        assert res.status_code == 200
        assert res.json()["email"] == self.user.email

    def test_token_is_single_use(self):
        token = self._create_deep_link_token()
        res1 = self.client.get(f"/agentic/login?token={token}")
        assert res1.status_code == 302
        assert "/project/" in res1["Location"]
        res2 = self.client.get(f"/agentic/login?token={token}")
        assert res2.status_code == 302
        assert "expired_or_invalid_token" in res2["Location"]

    @parameterized.expand(
        [
            ("missing_token", "", "missing_token"),
            ("invalid_token", "bogus", "expired_or_invalid_token"),
        ]
    )
    def test_error_redirect(self, _name: str, token_value: str, expected_error: str):
        url = "/agentic/login" if not token_value else f"/agentic/login?token={token_value}"
        res = self.client.get(url)
        assert res.status_code == 302
        assert expected_error in res["Location"]

    def test_without_team_id_redirects_to_root(self):
        token = "test_no_team_token"
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": self.user.id, "team_id": None},
            timeout=600,
        )
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert res["Location"] == "/"

    def test_expired_token_redirects_with_error(self):
        token = "test_expired_token"
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": self.user.id, "team_id": self.team.id},
            timeout=0,
        )
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert res["Location"] == "/?error=expired_or_invalid_token"

    def test_deleted_user_redirects_with_error(self):
        token = "test_deleted_user_token"
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": 999999, "team_id": self.team.id},
            timeout=600,
        )
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert res["Location"] == "/?error=user_not_found"

    def test_redirects_are_relative(self):
        token = self._create_deep_link_token()
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert not res["Location"].startswith("http")
