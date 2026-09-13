import json
import time

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.posthog_connection import CONNECTION_MAX_INFLIGHT_PER_CONNECTION
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.integration import Integration

FORWARD_PATH = "posthog.api.posthog_connection.requests.request"


def _mock_response(status_code: int, body: dict, chunks: list[bytes] | None = None) -> MagicMock:
    # The view streams the body via res.iter_content(...), so drive that rather than res.json().
    m = MagicMock(status_code=status_code)
    m.__enter__.return_value = m
    m.iter_content.return_value = iter(chunks) if chunks is not None else iter([json.dumps(body).encode()])
    return m


class TestPostHogConnectionForward:
    @pytest.fixture(autouse=True)
    def setup_environment(self, db, settings):
        # pytest-style class (not a Django TestCase), so use the `settings` fixture rather than the
        # override_settings class decorator, which only works on SimpleTestCase subclasses.
        settings.POSTHOG_CONNECT_BASE_URL_EU = "https://eu.posthog.com"
        settings.POSTHOG_CONNECT_OAUTH_CLIENT_ID_EU = "eu-client-id"
        settings.POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_EU = "eu-secret"
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(
            self.organization, "owner@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )
        self.other_user = User.objects.create_and_join(
            self.organization, "other@posthog.com", "test", level=OrganizationMembership.Level.ADMIN
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="posthog",
            integration_id="EU:user-uuid",
            created_by=self.user,
            config={"region": "EU", "refreshed_at": int(time.time()), "expires_in": 3600},
            sensitive_config={"refresh_token": "RT", "access_token": "AT"},
        )

    def _forward_url(self) -> str:
        return f"/api/environments/{self.team.pk}/posthog_connections/{self.integration.id}/forward/"

    def _target_url(self) -> str:
        return f"/api/environments/{self.team.pk}/posthog_connections/{self.integration.id}/target/"

    def test_forward_injects_token_and_passes_through(self, client: HttpClient):
        client.force_login(self.user)
        with patch(FORWARD_PATH) as mock_request:
            mock_request.return_value = _mock_response(200, {"results": [1, 2, 3]})

            response = client.post(
                self._forward_url(),
                {"method": "GET", "path": "api/projects/2/insights/", "query": {"limit": "5"}},
                content_type="application/json",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": 200, "data": {"results": [1, 2, 3]}}
        method, url = mock_request.call_args[0][0], mock_request.call_args[0][1]
        assert method == "GET"
        assert url == "https://eu.posthog.com/api/projects/2/insights/"
        assert mock_request.call_args[1]["headers"]["Authorization"] == "Bearer AT"
        assert mock_request.call_args[1]["params"] == {"limit": "5"}
        assert mock_request.call_args[1]["allow_redirects"] is False

    def test_forward_marks_the_target_as_mcp_only_for_mcp_origin(self, client: HttpClient):
        from posthog.auth import MCP_USER_AGENT_MARKER
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.utils import generate_random_token_personal, hash_key_value

        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="mcp", user=self.user, secure_value=hash_key_value(key_value), scopes=["*"])
        with patch(FORWARD_PATH) as mock_request:
            mock_request.return_value = _mock_response(201, {"id": "abc"})
            client.post(
                self._forward_url(),
                {"method": "POST", "path": "api/projects/2/tasks/", "data": {"description": "hi"}},
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {key_value}",
                headers={"User-Agent": f"cursor/1.0 {MCP_USER_AGENT_MARKER}; version: 1.0.0"},
            )
        assert MCP_USER_AGENT_MARKER in mock_request.call_args[1]["headers"]["User-Agent"]

        with patch(FORWARD_PATH) as mock_request:
            mock_request.return_value = _mock_response(201, {"id": "abc"})
            client.force_login(self.user)
            client.post(
                self._forward_url(),
                {"method": "POST", "path": "api/projects/2/tasks/", "data": {"description": "hi"}},
                content_type="application/json",
            )
        assert "User-Agent" not in mock_request.call_args[1]["headers"]

    def test_forward_sends_body_only_for_write_methods(self, client: HttpClient):
        client.force_login(self.user)
        with patch(FORWARD_PATH) as mock_request:
            mock_request.return_value = _mock_response(201, {"id": "abc"})

            client.post(
                self._forward_url(),
                {"method": "POST", "path": "api/projects/2/tasks/", "data": {"description": "hi"}},
                content_type="application/json",
            )

        assert mock_request.call_args[1]["json"] == {"description": "hi"}

    def test_forward_passes_through_target_error_status(self, client: HttpClient):
        client.force_login(self.user)
        with patch(FORWARD_PATH) as mock_request:
            mock_request.return_value = _mock_response(403, {"detail": "nope"})

            response = client.post(
                self._forward_url(),
                {"method": "GET", "path": "api/projects/2/insights/"},
                content_type="application/json",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": 403, "data": {"detail": "nope"}}

    @pytest.mark.parametrize("bad_path", ["../etc", "https://evil.com/x", "api/../../secret", "//evil.com"])
    def test_forward_rejects_unsafe_path(self, client: HttpClient, bad_path):
        client.force_login(self.user)
        with patch(FORWARD_PATH) as mock_request:
            response = client.post(
                self._forward_url(),
                {"method": "GET", "path": bad_path},
                content_type="application/json",
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_request.assert_not_called()

    def test_forward_rejects_non_creator(self, client: HttpClient):
        client.force_login(self.other_user)
        with patch(FORWARD_PATH) as mock_request:
            response = client.post(
                self._forward_url(),
                {"method": "GET", "path": "api/projects/2/insights/"},
                content_type="application/json",
            )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_request.assert_not_called()

    def test_forward_unknown_connection_is_404(self, client: HttpClient):
        client.force_login(self.user)
        response = client.post(
            f"/api/environments/{self.team.pk}/posthog_connections/nonexistent/forward/",
            {"method": "GET", "path": "api/projects/2/insights/"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_forward_unreachable_target_is_502(self, client: HttpClient):
        import requests

        client.force_login(self.user)
        with patch(FORWARD_PATH, side_effect=requests.ConnectionError("down")):
            response = client.post(
                self._forward_url(),
                {"method": "GET", "path": "api/projects/2/insights/"},
                content_type="application/json",
            )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    def test_forward_refuses_a_request_already_forwarded(self, client: HttpClient):
        # A request that arrived through a connection carries the marker header; forwarding it again
        # would let a connection be chained into itself.
        client.force_login(self.user)
        with patch(FORWARD_PATH) as mock_request:
            response = client.post(
                self._forward_url(),
                {"method": "GET", "path": "api/projects/2/insights/"},
                content_type="application/json",
                HTTP_X_POSTHOG_CONNECTION="1",
            )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_request.assert_not_called()

    def test_forward_requires_caller_token_to_cover_connection_scopes(self, client: HttpClient):
        # A scoped key that lacks the scopes the connection was granted can't wield the connection.
        self.integration.config["granted_scopes"] = ["insight:read", "task:write"]
        self.integration.save()
        client.force_login(self.user)
        with patch("posthog.api.posthog_connection.get_authenticator_scopes", return_value=["integration:write"]):
            with patch(FORWARD_PATH) as mock_request:
                response = client.post(
                    self._forward_url(),
                    {"method": "GET", "path": "api/projects/2/insights/"},
                    content_type="application/json",
                )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_request.assert_not_called()

    def test_forward_refuses_scoped_caller_when_granted_scopes_unknown(self, client: HttpClient):
        # If the target's token response omitted `scope`, `granted_scopes` is empty and we can't bound
        # what the connection can do — a scoped key must be refused rather than passing by default.
        self.integration.config["granted_scopes"] = []
        self.integration.save()
        client.force_login(self.user)
        with patch("posthog.api.posthog_connection.get_authenticator_scopes", return_value=["integration:write"]):
            with patch(FORWARD_PATH) as mock_request:
                response = client.post(
                    self._forward_url(),
                    {"method": "GET", "path": "api/projects/2/insights/"},
                    content_type="application/json",
                )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_request.assert_not_called()

    def test_forward_times_out_when_target_exceeds_deadline(self, client: HttpClient):
        # A target that keeps trickling data past the wall-clock deadline is cut off with a 504 rather
        # than holding a worker (and its in-flight slot) open past the lease.
        client.force_login(self.user)
        slow = _mock_response(200, {}, chunks=[b'{"a":1}', b"more"])
        # deadline = 0 + timeout; the post-chunk check sees a clock already past it.
        with patch("posthog.api.posthog_connection.monotonic", side_effect=[0.0, 10_000.0, 10_001.0]):
            with patch(FORWARD_PATH, return_value=slow):
                response = client.post(
                    self._forward_url(),
                    {"method": "GET", "path": "api/projects/2/insights/"},
                    content_type="application/json",
                )
        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT

    def test_forward_returns_502_when_response_exceeds_size_cap(self, client: HttpClient):
        # A target returning more than the response cap is cut off and reported as a gateway error
        # rather than buffering an unbounded body into a worker.
        client.force_login(self.user)
        big = _mock_response(200, {}, chunks=[b'{"a":1}', b"overflow"])
        with patch("posthog.api.posthog_connection.CONNECTION_MAX_RESPONSE_BYTES", 8):
            with patch(FORWARD_PATH, return_value=big):
                response = client.post(
                    self._forward_url(),
                    {"method": "GET", "path": "api/projects/2/insights/"},
                    content_type="application/json",
                )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "too large" in response.json()["data"]["error"]

    def test_forward_passes_through_non_json_body_as_null(self, client: HttpClient):
        # A target response that isn't JSON (an HTML error page, say) passes its status through with a
        # null body rather than raising a decode error and 500-ing the proxy.
        client.force_login(self.user)
        with patch(FORWARD_PATH, return_value=_mock_response(500, {}, chunks=[b"<html>nope</html>"])):
            response = client.post(
                self._forward_url(),
                {"method": "GET", "path": "api/projects/2/insights/"},
                content_type="application/json",
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": 500, "data": None}

    def test_forward_rejects_when_connection_at_inflight_capacity(self, client: HttpClient):
        # The per-minute throttle limits how fast forwards start, not how many run at once. When a
        # connection is already at its in-flight cap, a new forward is refused before the outbound call.
        client.force_login(self.user)
        with patch(
            "posthog.api.posthog_connection.cache.incr", return_value=CONNECTION_MAX_INFLIGHT_PER_CONNECTION + 1
        ):
            with patch(FORWARD_PATH) as mock_request:
                response = client.post(
                    self._forward_url(),
                    {"method": "GET", "path": "api/projects/2/insights/"},
                    content_type="application/json",
                )
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        mock_request.assert_not_called()

    def test_target_reports_the_connected_project_not_the_local_one(self, client: HttpClient):
        # Callers build target API paths from this, so it must report the far side. Reporting the
        # local project id would send every subsequent forward to a project that isn't there.
        client.force_login(self.user)
        me = {
            "team": {"id": 4242, "name": "EU Team"},
            "organization": {"id": "org-uuid", "name": "EU Org"},
        }
        with patch(FORWARD_PATH, return_value=_mock_response(200, me)) as mock_request:
            response = client.get(self._target_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "project_id": 4242,
            "project_name": "EU Team",
            "organization_id": "org-uuid",
            "organization_name": "EU Org",
            "region": "EU",
            "base_url": "https://eu.posthog.com",
        }
        assert mock_request.call_args[0][1] == "https://eu.posthog.com/api/users/@me/"

    @pytest.mark.parametrize(
        "status_code,body",
        [
            (200, {"organization": {"id": "org-uuid"}}),
            (401, {"detail": "Invalid token"}),
            (200, {}),
        ],
    )
    def test_target_fails_closed_when_the_far_side_has_no_project(self, client: HttpClient, status_code, body):
        # Half-resolving is worse than not resolving: a caller trusting a missing project id would
        # build `api/projects/None/...` paths and blame the target for the 404.
        client.force_login(self.user)
        with patch(FORWARD_PATH, return_value=_mock_response(status_code, body)):
            response = client.get(self._target_url())

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "error" in response.json()

    def test_target_caches_the_resolved_identity(self, client: HttpClient):
        # The connected project's identity changes only on reconnect, so it's cached — a second read
        # must not round-trip to the target again.
        client.force_login(self.user)
        me = {"team": {"id": 4242, "name": "EU Team"}, "organization": {"id": "org-uuid", "name": "EU Org"}}
        with patch(FORWARD_PATH, return_value=_mock_response(200, me)) as mock_request:
            first = client.get(self._target_url())
            second = client.get(self._target_url())

        assert first.status_code == status.HTTP_200_OK
        assert second.json() == first.json()
        assert mock_request.call_count == 1

    def test_target_survives_a_cache_outage(self, client: HttpClient):
        # Reading the identity fails open if the cache is down — a cache outage can't take the feature
        # offline, it just costs the round trip the cache would have saved. Fault is scoped to this
        # view's own key so unrelated cache users (middleware) keep working.
        client.force_login(self.user)
        me = {"team": {"id": 4242, "name": "EU Team"}, "organization": {"id": "org-uuid", "name": "EU Org"}}
        real_get, real_set = cache.get, cache.set

        def failing_get(key, *args, **kwargs):
            if str(key).startswith("posthog_connection_target:"):
                raise Exception("cache down")
            return real_get(key, *args, **kwargs)

        def failing_set(key, *args, **kwargs):
            if str(key).startswith("posthog_connection_target:"):
                raise Exception("cache down")
            return real_set(key, *args, **kwargs)

        with patch("posthog.api.posthog_connection.cache.get", side_effect=failing_get):
            with patch("posthog.api.posthog_connection.cache.set", side_effect=failing_set):
                with patch(FORWARD_PATH, return_value=_mock_response(200, me)):
                    response = client.get(self._target_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["project_id"] == 4242

    def test_target_rejects_non_creator(self, client: HttpClient):
        # The connection acts as its creator, so reading where it points is as restricted as using it.
        client.force_login(self.other_user)
        with patch(FORWARD_PATH) as mock_request:
            response = client.get(self._target_url())

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_request.assert_not_called()

    def test_target_refuses_a_request_already_forwarded(self, client: HttpClient):
        # Same anti-chaining rule as forward — a connection must not be reachable one hop in.
        client.force_login(self.user)
        with patch(FORWARD_PATH) as mock_request:
            response = client.get(self._target_url(), headers={"X-PostHog-Connection": "1"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_request.assert_not_called()
