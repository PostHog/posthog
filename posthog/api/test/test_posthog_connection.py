import json
import time
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test.client import Client as HttpClient
from django.utils import timezone

from rest_framework import status

from posthog.api.posthog_connection import CONNECTION_MAX_INFLIGHT_PER_CONNECTION
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.oauth_provenance import SANDBOX_ORIGIN_HEADER
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

FORWARD_PATH = "posthog.api.posthog_connection.requests.request"


def _mock_response(status_code: int, body: dict, chunks: list[bytes] | None = None) -> MagicMock:
    # The view streams the body via res.iter_content(...), so drive that rather than res.json().
    m = MagicMock(status_code=status_code)
    m.headers = {}
    m.__enter__.return_value = m
    # A fresh iterator per read, so one mock can answer several requests and survive a test rerun.
    payload = chunks if chunks is not None else [json.dumps(body).encode()]
    m.iter_content.side_effect = lambda *args, **kwargs: iter(payload)
    return m


ME_URL = "https://eu.posthog.com/api/users/@me/"
INTROSPECT_URL = "https://eu.posthog.com/oauth/introspect/"
CURRENT_ORG = {
    "id": "org-current",
    "name": "Demo Org",
    "teams": [{"id": 4242, "name": "Demo Team"}, {"id": 4343, "name": "Other Team"}],
}
ME = {
    "team": {"id": 4242, "name": "Demo Team"},
    "organization": CURRENT_ORG,
    "organizations": [{"id": "org-current", "name": "Demo Org"}, {"id": "org-internal", "name": "Internal Org"}],
}


def _target_side(responses: dict[str, MagicMock]):
    # Answer each far-side URL the target endpoint reads; any other URL is a bug in the test.
    def side_effect(method: str, url: str, **kwargs):
        return responses[url]

    return side_effect


def _introspection(scoped_teams: list[int]) -> MagicMock:
    return _mock_response(200, {"active": True, "scoped_teams": scoped_teams, "scoped_organizations": []})


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

    @pytest.mark.parametrize("private", [True, False])
    @pytest.mark.parametrize("target_status", [200, 403, 500])
    def test_forward_preserves_trusted_capture_policy(
        self, client: HttpClient, private: bool, target_status: int
    ) -> None:
        client.force_login(self.user)
        upstream = _mock_response(target_status, {"detail": "Synthetic response"})
        if private:
            upstream.headers["X-PostHog-Suppress-Analytics"] = "true"
        with patch(FORWARD_PATH, return_value=upstream):
            response = client.post(
                self._forward_url(),
                {"method": "GET", "path": "api/projects/2/tasks/"},
                content_type="application/json",
                headers={"X-PostHog-Suppress-Analytics": "true"},
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == target_status
        assert (response.get("X-PostHog-Suppress-Analytics") == "true") == private

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

    @pytest.mark.parametrize("sandbox", [False, True])
    def test_forward_preserves_sandbox_origin(self, client: HttpClient, sandbox: bool):
        application = OAuthApplication.objects.create(
            name="Connection client",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            algorithm="RS256",
            redirect_uris="https://example.com/callback",
            user=self.user,
            organization=self.organization,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_connection_caller_token",
            expires=timezone.now() + timedelta(hours=1),
            scope="integration:write task:write" + (" internal_run:read" if sandbox else ""),
            scoped_teams=[self.team.id],
        )
        self.integration.config["granted_scopes"] = ["task:write"]
        self.integration.save(update_fields=["config"])

        with patch(FORWARD_PATH) as mock_request:
            mock_request.return_value = _mock_response(200, {})
            response = client.post(
                self._forward_url(),
                {"method": "POST", "path": "api/projects/2/tasks/", "data": {"start_run": True}},
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token.token}",
            )

        assert response.status_code == status.HTTP_200_OK
        headers = mock_request.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer AT"
        assert headers.get(SANDBOX_ORIGIN_HEADER) == ("1" if sandbox else None)

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

    @pytest.mark.parametrize(
        "granted_scopes,caller_scopes,forwarded",
        [
            (["insight:read", "task:write"], ["integration:write"], False),
            (
                ["task:read", "task:write", "inbox:read", "inbox:write"],
                ["integration:write", "task:read", "task:write"],
                True,
            ),
            (["task:read", "task:write", "inbox:read", "inbox:write"], ["integration:write", "inbox:write"], False),
        ],
    )
    def test_forward_requires_caller_token_to_cover_connection_scopes(
        self, client: HttpClient, granted_scopes: list[str], caller_scopes: list[str], forwarded: bool
    ):
        self.integration.config["granted_scopes"] = granted_scopes
        self.integration.save()
        client.force_login(self.user)
        with patch("posthog.api.posthog_connection.get_authenticator_scopes", return_value=caller_scopes):
            with patch(FORWARD_PATH) as mock_request:
                mock_request.return_value = _mock_response(200, {"results": []})
                response = client.post(
                    self._forward_url(),
                    {"method": "GET", "path": "api/projects/2/insights/"},
                    content_type="application/json",
                )
        assert response.status_code == (status.HTTP_200_OK if forwarded else status.HTTP_403_FORBIDDEN)
        assert mock_request.called == forwarded

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
        responses = {ME_URL: _mock_response(200, me), INTROSPECT_URL: _introspection([])}
        with patch(FORWARD_PATH, side_effect=_target_side(responses)):
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

    @pytest.mark.parametrize(
        "introspection,project_response,expected",
        [
            pytest.param(_introspection([]), None, (4242, "Demo Team", "org-current", "Demo Org"), id="unscoped_token"),
            pytest.param(
                _introspection([4242]),
                None,
                (4242, "Demo Team", "org-current", "Demo Org"),
                id="scoped_to_current_project",
            ),
            pytest.param(
                _introspection([4343]),
                None,
                (4343, "Other Team", "org-current", "Demo Org"),
                id="scoped_to_other_project_in_current_org",
            ),
            pytest.param(
                _introspection([1]),
                _mock_response(200, {"id": 1, "name": "Internal Team", "organization": "org-internal"}),
                (1, "Internal Team", "org-internal", "Internal Org"),
                id="scoped_to_project_in_other_org",
            ),
        ],
    )
    def test_target_uses_the_project_picked_at_consent(
        self, client: HttpClient, introspection, project_response, expected
    ):
        # The token works only in the projects picked at consent. The user's current project on the
        # far side can be another one, and resolving to it sends every call where the token is refused.
        client.force_login(self.user)
        responses = {ME_URL: _mock_response(200, ME), INTROSPECT_URL: introspection}
        if project_response is not None:
            responses["https://eu.posthog.com/api/projects/1/"] = project_response
        with patch(FORWARD_PATH, side_effect=_target_side(responses)):
            response = client.get(self._target_url())

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert (
            body["project_id"],
            body["project_name"],
            body["organization_id"],
            body["organization_name"],
        ) == expected

    @pytest.mark.parametrize(
        "introspection,project_status,error_fragment",
        [
            pytest.param(_introspection([1, 2]), None, "switch to the project you want", id="several_scoped_projects"),
            pytest.param(_introspection([1]), 403, "switch to project 1", id="scoped_project_unreadable"),
            pytest.param(
                _mock_response(503, {"detail": "unavailable"}), None, "could not be read", id="introspection_down"
            ),
            pytest.param(
                _mock_response(200, {"active": False}), None, "could not be read", id="introspection_inactive"
            ),
            pytest.param(
                _mock_response(200, {"active": True, "scoped_teams": ["1"]}),
                None,
                "could not be read",
                id="introspection_malformed",
            ),
        ],
    )
    def test_target_explains_a_consent_it_cannot_resolve(
        self, client: HttpClient, introspection, project_status, error_fragment
    ):
        client.force_login(self.user)
        responses = {ME_URL: _mock_response(200, ME), INTROSPECT_URL: introspection}
        if project_status is not None:
            responses["https://eu.posthog.com/api/projects/1/"] = _mock_response(project_status, {"detail": "no"})
        with patch(FORWARD_PATH, side_effect=_target_side(responses)):
            response = client.get(self._target_url())

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert error_fragment in response.json()["error"]

    def test_target_does_not_cache_an_unknown_consent(self, client: HttpClient):
        # Caching the current project while introspection is down would keep sending calls where
        # the token is refused after introspection recovers.
        client.force_login(self.user)
        down = {ME_URL: _mock_response(200, ME), INTROSPECT_URL: _mock_response(503, {"detail": "unavailable"})}
        with patch(FORWARD_PATH, side_effect=_target_side(down)):
            failed = client.get(self._target_url())

        recovered = {ME_URL: _mock_response(200, ME), INTROSPECT_URL: _introspection([4343])}
        with patch(FORWARD_PATH, side_effect=_target_side(recovered)):
            after = client.get(self._target_url())

        assert failed.status_code == status.HTTP_502_BAD_GATEWAY
        assert after.json()["project_id"] == 4343

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
        responses = {ME_URL: _mock_response(200, ME), INTROSPECT_URL: _introspection([])}
        with patch(FORWARD_PATH, side_effect=_target_side(responses)) as mock_request:
            first = client.get(self._target_url())
            calls_for_first = mock_request.call_count
            second = client.get(self._target_url())

        assert first.status_code == status.HTTP_200_OK
        assert second.json() == first.json()
        assert mock_request.call_count == calls_for_first

    def test_target_resolves_again_after_a_reconnect(self, client: HttpClient):
        # A reconnect can pick another project at consent, and the old answer must not outlive it.
        client.force_login(self.user)
        with patch(
            FORWARD_PATH,
            side_effect=_target_side({ME_URL: _mock_response(200, ME), INTROSPECT_URL: _introspection([])}),
        ):
            before = client.get(self._target_url())

        self.integration.config = {**self.integration.config, "refreshed_at": int(time.time()) + 1}
        self.integration.save()
        with patch(
            FORWARD_PATH,
            side_effect=_target_side({ME_URL: _mock_response(200, ME), INTROSPECT_URL: _introspection([4343])}),
        ):
            after = client.get(self._target_url())

        assert before.json()["project_id"] == 4242
        assert after.json()["project_id"] == 4343

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
                with patch(
                    FORWARD_PATH,
                    side_effect=_target_side({ME_URL: _mock_response(200, me), INTROSPECT_URL: _introspection([])}),
                ):
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
