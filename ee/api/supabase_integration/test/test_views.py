from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from ee.api.supabase_integration import STATE_CACHE_PREFIX, TOKEN_CACHE_PREFIX

TEST_CLIENT_ID = "test-supabase-client-id"
TEST_CLIENT_SECRET = "test-supabase-client-secret"
TEST_API_BASE_URL = "https://api.supabase.com/v1"


@override_settings(
    SUPABASE_OAUTH_CLIENT_ID=TEST_CLIENT_ID,
    SUPABASE_OAUTH_CLIENT_SECRET=TEST_CLIENT_SECRET,
    SUPABASE_API_BASE_URL=TEST_API_BASE_URL,
)
class TestSupabaseInstall(APIBaseTest):
    def test_redirects_to_supabase_authorize(self):
        res = self.client.get("/integrations/supabase/install")
        assert res.status_code == 302
        parsed = urlparse(res["Location"])
        assert parsed.scheme == "https"
        assert parsed.hostname == "api.supabase.com"
        assert parsed.path == "/v1/oauth/authorize"
        params = parse_qs(parsed.query)
        assert params["client_id"] == [TEST_CLIENT_ID]
        assert params["response_type"] == ["code"]
        assert "state" in params

    def test_caches_state_with_user_id(self):
        res = self.client.get("/integrations/supabase/install")
        parsed = urlparse(res["Location"])
        params = parse_qs(parsed.query)
        state = params["state"][0]
        cached_user_id = cache.get(f"{STATE_CACHE_PREFIX}{state}")
        assert cached_user_id == self.user.id

    def test_redirect_uri_points_to_callback(self):
        res = self.client.get("/integrations/supabase/install")
        parsed = urlparse(res["Location"])
        params = parse_qs(parsed.query)
        redirect_uri = params["redirect_uri"][0]
        assert redirect_uri.endswith("/integrations/supabase/callback")

    def test_requires_login(self):
        self.client.logout()
        res = self.client.get("/integrations/supabase/install")
        assert res.status_code == 302
        assert "/login" in res["Location"]


@override_settings(
    SUPABASE_OAUTH_CLIENT_ID=TEST_CLIENT_ID,
    SUPABASE_OAUTH_CLIENT_SECRET=TEST_CLIENT_SECRET,
    SUPABASE_API_BASE_URL=TEST_API_BASE_URL,
)
class TestSupabaseCallback(APIBaseTest):
    def test_rejects_missing_code(self):
        res = self.client.get("/integrations/supabase/callback?state=abc")
        assert res.status_code == 400

    def test_rejects_missing_state(self):
        res = self.client.get("/integrations/supabase/callback?code=abc")
        assert res.status_code == 400

    def test_rejects_invalid_state(self):
        res = self.client.get("/integrations/supabase/callback?code=abc&state=invalid")
        assert res.status_code == 400

    @patch("ee.api.supabase_integration.views.external_requests")
    def test_exchanges_code_for_tokens(self, mock_requests: MagicMock):
        state = "valid_state"
        cache.set(f"{STATE_CACHE_PREFIX}{state}", self.user.id, timeout=600)

        token_response = MagicMock()
        token_response.json.return_value = {
            "access_token": "sb_access_token",
            "refresh_token": "sb_refresh_token",
        }
        token_response.raise_for_status = MagicMock()

        orgs_response = MagicMock()
        orgs_response.json.return_value = [{"id": "org_1", "name": "Test Org"}]
        orgs_response.raise_for_status = MagicMock()

        mock_requests.post.return_value = token_response
        mock_requests.get.return_value = orgs_response

        res = self.client.get(f"/integrations/supabase/callback?code=test_code&state={state}")

        assert res.status_code == 302
        assert res["Location"] == "/project/settings?supabase=connected"

        mock_requests.post.assert_called_once()
        call_kwargs = mock_requests.post.call_args
        assert call_kwargs[0][0] == f"{TEST_API_BASE_URL}/oauth/token"
        assert call_kwargs[1]["data"]["grant_type"] == "authorization_code"
        assert call_kwargs[1]["data"]["code"] == "test_code"

    @patch("ee.api.supabase_integration.views.external_requests")
    def test_stores_tokens_in_cache(self, mock_requests: MagicMock):
        state = "token_state"
        cache.set(f"{STATE_CACHE_PREFIX}{state}", self.user.id, timeout=600)

        token_response = MagicMock()
        token_response.json.return_value = {
            "access_token": "sb_access",
            "refresh_token": "sb_refresh",
        }
        token_response.raise_for_status = MagicMock()

        orgs_response = MagicMock()
        orgs_response.json.return_value = [{"id": "org_1"}]
        orgs_response.raise_for_status = MagicMock()

        mock_requests.post.return_value = token_response
        mock_requests.get.return_value = orgs_response

        self.client.get(f"/integrations/supabase/callback?code=test_code&state={state}")

        cached = cache.get(f"{TOKEN_CACHE_PREFIX}{self.user.id}")
        assert cached is not None
        assert cached["access_token"] == "sb_access"
        assert cached["refresh_token"] == "sb_refresh"
        assert cached["supabase_orgs"] == [{"id": "org_1"}]

    @patch("ee.api.supabase_integration.views.external_requests")
    def test_deletes_state_after_use(self, mock_requests: MagicMock):
        state = "one_time_state"
        cache.set(f"{STATE_CACHE_PREFIX}{state}", self.user.id, timeout=600)

        token_response = MagicMock()
        token_response.json.return_value = {"access_token": "t", "refresh_token": "r"}
        token_response.raise_for_status = MagicMock()

        orgs_response = MagicMock()
        orgs_response.json.return_value = []
        orgs_response.raise_for_status = MagicMock()

        mock_requests.post.return_value = token_response
        mock_requests.get.return_value = orgs_response

        self.client.get(f"/integrations/supabase/callback?code=test_code&state={state}")

        assert cache.get(f"{STATE_CACHE_PREFIX}{state}") is None

    @patch("ee.api.supabase_integration.views.external_requests")
    def test_handles_token_exchange_failure(self, mock_requests: MagicMock):
        state = "fail_state"
        cache.set(f"{STATE_CACHE_PREFIX}{state}", self.user.id, timeout=600)

        mock_requests.post.side_effect = Exception("Connection error")

        res = self.client.get(f"/integrations/supabase/callback?code=test_code&state={state}")

        assert res.status_code == 502

    @patch("ee.api.supabase_integration.views.external_requests")
    def test_handles_orgs_fetch_failure_gracefully(self, mock_requests: MagicMock):
        state = "orgs_fail_state"
        cache.set(f"{STATE_CACHE_PREFIX}{state}", self.user.id, timeout=600)

        token_response = MagicMock()
        token_response.json.return_value = {"access_token": "t", "refresh_token": "r"}
        token_response.raise_for_status = MagicMock()

        mock_requests.post.return_value = token_response
        mock_requests.get.side_effect = Exception("Orgs fetch failed")

        res = self.client.get(f"/integrations/supabase/callback?code=test_code&state={state}")

        assert res.status_code == 302
        cached = cache.get(f"{TOKEN_CACHE_PREFIX}{self.user.id}")
        assert cached is not None
        assert cached["supabase_orgs"] == []
