from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase
from ee.api.agentic_provisioning.views import DEEP_LINK_CACHE_PREFIX


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestDeepLinks(ProvisioningTestBase):
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

    @patch("ee.api.agentic_provisioning.views._capture_provisioning_event")
    def test_deep_link_capture_attributes_client(self, mock_capture_event):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"purpose": "dashboard"},
            token=token,
        )
        assert res.status_code == 200

        success_calls = [
            call for call in mock_capture_event.call_args_list if call.args[:2] == ("deep_link_created", "success")
        ]
        assert len(success_calls) == 1
        partner = success_calls[0].kwargs["partner"]
        assert partner is not None
        assert partner.name == "PostHog Stripe App"

    def test_deep_link_missing_bearer_returns_401(self):
        res = self._post_signed("/api/agentic/provisioning/deep_links", data={"purpose": "dashboard"})
        assert res.status_code == 401

    def test_deep_link_denied_when_partner_not_allowed(self):
        from posthog.models.oauth import OAuthApplication

        from ee.api.agentic_provisioning.test.base import TEST_STRIPE_OAUTH_CLIENT_ID

        token = self._get_bearer_token()
        OAuthApplication.objects.filter(client_id=TEST_STRIPE_OAUTH_CLIENT_ID).update(
            provisioning_can_issue_deep_links=False
        )
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"purpose": "dashboard"},
            token=token,
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "deep_links_not_enabled"

    def test_deep_link_with_path_redirects_there(self):
        token = self._get_bearer_token()
        target = f"/project/{self.team.id}/replay/019e6d10-c3b0-7000-8000-000000000000"
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"path": target},
            token=token,
        )
        assert res.status_code == 200

        self.user.is_email_verified = True
        self.user.save(update_fields=["is_email_verified"])

        login_token = res.json()["url"].split("token=")[1].split("&")[0]
        login_res = self.client.get(f"/agentic/login?token={login_token}")
        assert login_res.status_code == 302
        assert login_res["Location"] == target

    @parameterized.expand(
        [
            ("protocol_relative", "//evil.com"),
            ("absolute_url", "https://evil.com/steal"),
            ("backslash_host", "/\\evil.com"),
            ("javascript_scheme", "javascript:alert(1)"),
            ("not_rooted", "project/123/insights"),
            ("crlf_header_injection", "/project/1\r\nLocation: https://evil.com"),
            ("newline", "/project/1\nreplay"),
            ("tab", "/project/1\treplay"),
            ("space", "/project/1 replay"),
            ("null_byte", "/project/1\x00"),
        ]
    )
    def test_deep_link_rejects_unsafe_path(self, _name: str, path: str):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"path": path},
            token=token,
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_path"

    def test_deep_link_requires_hmac_signature_for_hmac_partner(self):
        from posthog.models.oauth import OAuthApplication

        from ee.api.agentic_provisioning.test.base import TEST_STRIPE_OAUTH_CLIENT_ID

        token = self._get_bearer_token()
        OAuthApplication.objects.filter(client_id=TEST_STRIPE_OAUTH_CLIENT_ID).update(
            provisioning_auth_method="hmac",
            provisioning_active=True,
            provisioning_can_provision_resources=True,
        )
        res = self.client.post(
            "/api/agentic/provisioning/deep_links",
            data={"purpose": "dashboard"},
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "hmac_signature_required"


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestAgenticLogin(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        # Default test user is is_email_verified=None; happy-path tests in this class
        # assume a verified user. Unverified scenarios opt in explicitly.
        self.user.is_email_verified = True
        self.user.save(update_fields=["is_email_verified"])

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

    @parameterized.expand(
        [
            ("false", False),
            ("null_legacy", None),
        ]
    )
    def test_unverified_user_redirects_to_verify_email(self, _name, verified_value):
        # Both False (new partner account) and None (legacy NULL passthrough) must be
        # blocked - deep-link login has no password challenge.
        self.user.is_email_verified = verified_value
        self.user.save(update_fields=["is_email_verified"])
        token = self._create_deep_link_token()
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert res["Location"] == f"/verify_email/{self.user.uuid}"

    def test_unverified_user_does_not_create_session(self):
        self.user.is_email_verified = False
        self.user.save(update_fields=["is_email_verified"])
        token = self._create_deep_link_token()
        self.client.get(f"/agentic/login?token={token}")
        res = self.client.get("/api/users/@me/")
        assert res.status_code == 401

    def test_path_token_redirects_to_path(self):
        token = "test_path_token"
        target = f"/project/{self.team.id}/replay/abc123-DEF"
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": self.user.id, "team_id": self.team.id, "path": target},
            timeout=600,
        )
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert res["Location"] == target

    def test_unsafe_path_in_cache_falls_back_to_project(self):
        token = "test_unsafe_path_token"
        cache.set(
            f"{DEEP_LINK_CACHE_PREFIX}{token}",
            {"user_id": self.user.id, "team_id": self.team.id, "path": "//evil.com"},
            timeout=600,
        )
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert res["Location"] == f"/project/{self.team.id}"

    def test_verified_user_logs_in(self):
        token = self._create_deep_link_token()
        res = self.client.get(f"/agentic/login?token={token}")
        assert res.status_code == 302
        assert res["Location"] == f"/project/{self.team.id}"
