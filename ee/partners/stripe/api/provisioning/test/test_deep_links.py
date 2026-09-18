from urllib.parse import parse_qs, urlparse

from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from ee.partners.stripe.api.provisioning import DEEP_LINK_CACHE_PREFIX
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

DEEP_LINKS_URL = f"{BASE_PATH}/provisioning/deep_links"
LOGIN_URL = f"{BASE_PATH}/login"


class TestDeepLinks(StripeProvisioningTestBase):
    def _cache_deep_link_token(self, token: str) -> None:
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": self.user.id, "team_id": self.team.id},
            timeout=600,
        )

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
            ("false", False),
            ("null_legacy", None),
        ]
    )
    @patch("ee.partners.stripe.api.provisioning.login.email_verification_code_verifier.send_code")
    def test_unverified_user_lands_on_verify_email_with_a_reason(self, _name, verified_value, _mock_send_code):
        self.user.is_email_verified = verified_value
        self.user.save(update_fields=["is_email_verified"])
        self._cache_deep_link_token("stripe_unverified_token")

        res = self.client.get(f"{LOGIN_URL}?token=stripe_unverified_token")

        assert res.status_code == 302
        assert res["Location"] == f"/verify_email/{self.user.uuid}?reason=stripe_deep_link"

    @patch(
        "ee.partners.stripe.api.provisioning.login.email_verification_code_verifier.send_code",
        side_effect=Exception("smtp down"),
    )
    def test_failed_verification_email_is_flagged_to_the_page(self, _mock_send_code):
        self.user.is_email_verified = False
        self.user.save(update_fields=["is_email_verified"])
        self._cache_deep_link_token("stripe_send_failure_token")

        res = self.client.get(f"{LOGIN_URL}?token=stripe_send_failure_token")

        assert res.status_code == 302
        assert res["Location"] == f"/verify_email/{self.user.uuid}?reason=stripe_deep_link&email_sent=false"

    def test_deep_link_refused_when_the_application_cannot_issue_them(self):
        self.stripe_app.update_provisioning(can_issue_deep_links=False)
        token = self._get_bearer_token()

        res = self._post_signed_with_bearer(DEEP_LINKS_URL, data={"purpose": "dashboard"}, token=token)

        assert res.status_code == 403
        assert res.json()["error"]["code"] == "deep_links_not_enabled"

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
