import json
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user_integration import UserIntegration
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.canvas.backend.connectors import MAX_RESULT_BYTES, _bounded
from products.canvas.backend.models import Canvas
from products.canvas.backend.tests.test_canvas_api import CanvasAPIBaseTest
from products.tasks.backend.models import Task

_GITHUB_PR = {
    "number": 7,
    "title": "feat: thing",
    "html_url": "https://github.com/example/app/pull/7",
    "state": "open",
    "draft": False,
    "user": {"login": "octocat"},
    "head": {"ref": "feat"},
    "base": {"ref": "main"},
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
}


def _github_response(status_code: int = 200, payload: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else [_GITHUB_PR]
    return response


class TestCanvasConnectors(CanvasAPIBaseTest):
    def setUp(self):
        super().setUp()
        enabled = patch("products.canvas.backend.presentation.views.canvas_connectors_enabled", return_value=True)
        enabled.start()
        self.addCleanup(enabled.stop)

    def _connectors_canvas(self, connectors: list[dict[str, Any]] | None = None) -> str:
        canvas_id = self._create_canvas()
        capabilities = {
            "posthog": {"insights": [], "inlineQueries": False, "captureEvents": [], "state": [], "actions": []},
            "network": {"origins": []},
            "connectors": connectors
            if connectors is not None
            else [{"provider": "github", "tools": ["list_pull_requests", "search_issues"]}],
        }
        response = self._publish(canvas_id, project=self._project(capabilities=capabilities))
        assert response.status_code == status.HTTP_200_OK, response.json()
        return canvas_id

    def _connect_github(self) -> UserIntegration:
        return UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="12345",
            config={"installation_id": "12345", "account": {"type": "User", "name": "octocat"}},
            sensitive_config={"access_token": "ghs_test", "user_access_token": "ghu_test"},
        )

    def _call(self, canvas_id: str, provider: str = "github", tool: str = "list_pull_requests", **arguments: Any):
        return self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/connectors/call/",
            {"provider": provider, "tool": tool, "arguments": arguments or {"repository": "app"}},
            format="json",
        )

    @patch("products.canvas.backend.connectors.UserGitHubIntegration.api_request", return_value=_github_response())
    def test_declared_github_tool_runs_with_the_viewers_connection_and_is_audited(self, mock_request):
        canvas_id = self._connectors_canvas()
        self._connect_github()

        response = self._call(canvas_id, repository="example/app", state="open")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["status"] == "ok"
        assert body["truncated"] is False
        assert body["result"]["pull_requests"][0] == {
            "number": 7,
            "title": "feat: thing",
            "url": "https://github.com/example/app/pull/7",
            "state": "open",
            "draft": False,
            "author": "octocat",
            "head_branch": "feat",
            "base_branch": "main",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
        }
        assert mock_request.call_args.args[1] == "/repos/example/app/pulls"
        entries = self._activity("connector_tool_called")
        assert len(entries) == 1
        assert entries[0].detail is not None
        assert entries[0].detail["trigger"]["payload"] == {
            "provider": "github",
            "tool": "list_pull_requests",
            "status": "ok",
        }

    @patch("products.canvas.backend.connectors.UserGitHubIntegration.api_request", return_value=_github_response())
    def test_bare_repository_name_resolves_against_the_connections_account(self, mock_request):
        canvas_id = self._connectors_canvas()
        self._connect_github()

        assert self._call(canvas_id, repository="app").status_code == status.HTTP_200_OK
        assert mock_request.call_args.args[1] == "/repos/octocat/app/pulls"

    def test_viewer_without_a_connection_is_told_where_to_connect(self):
        canvas_id = self._connectors_canvas()

        response = self._call(canvas_id)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "not_connected"
        assert body["result"] is None
        assert body["connect_path"] == "/settings/user-personal-integrations"

    @parameterized.expand(
        [
            ("undeclared_tool", "github", "get_file_contents"),
            ("undeclared_provider", "mcp:mcp.example.com", "list_events"),
        ]
    )
    @patch("products.canvas.backend.connectors.UserGitHubIntegration.api_request")
    def test_undeclared_calls_are_refused_before_any_upstream_call(self, _name, provider, tool, mock_request):
        canvas_id = self._connectors_canvas()
        self._connect_github()

        response = self._call(canvas_id, provider=provider, tool=tool)

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_request.assert_not_called()
        assert self._activity("connector_tool_called") == []

    def test_invalid_arguments_are_rejected_by_the_tools_schema(self):
        canvas_id = self._connectors_canvas()
        self._connect_github()

        response = self._call(canvas_id, repository="../evil", state="open")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "repository"

    @parameterized.expand(
        [
            ("http_error", "list_pull_requests", 502, {}, None),
            ("invalid_json", "list_pull_requests", 200, {}, ValueError("invalid JSON")),
            ("invalid_list", "list_pull_requests", 200, {}, None),
            ("missing_fields", "list_pull_requests", 200, [{}], None),
            ("invalid_issues", "search_issues", 200, [], None),
            ("invalid_file", "get_file_contents", 200, [], None),
            ("invalid_base64", "get_file_contents", 200, {"encoding": "base64", "content": "!"}, None),
        ]
    )
    @patch("products.canvas.backend.connectors.UserGitHubIntegration.api_request")
    def test_upstream_failures_surface_as_a_status_not_a_500(self, _name, tool, code, body, error, mock_request):
        canvas_id = self._connectors_canvas([{"provider": "github", "tools": [tool]}])
        self._connect_github()
        mock_request.return_value = _github_response(code, body)
        mock_request.return_value.json.side_effect = error

        response = self._call(canvas_id, tool=tool, repository="example/app", query="bug", file_path="README.md")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "upstream_error"

    def test_disabled_flag_refuses_every_call(self):
        canvas_id = self._connectors_canvas()
        self._connect_github()
        with patch("products.canvas.backend.presentation.views.canvas_connectors_enabled", return_value=False):
            assert self._call(canvas_id).status_code == status.HTTP_403_FORBIDDEN

    def test_sandbox_tokens_cannot_call_connectors(self):
        canvas_id = self._connectors_canvas()
        task = Task.objects.create(
            team=self.team,
            channel=self.channel,
            created_by=self.user,
            title="Connectors",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        Canvas.objects.unscoped().filter(id=canvas_id).update(generation_task_id=task.id)

        response = self._sandbox_client(task.id).post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/connectors/call/",
            {"provider": "github", "tool": "list_pull_requests", "arguments": {"repository": "app"}},
            format="json",
            HTTP_X_POSTHOG_TASK_ID=str(task.id),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_mcp_provider_without_a_connection_points_at_the_mcp_store(self):
        canvas_id = self._connectors_canvas([{"provider": "mcp:mcp.example.com", "tools": ["list_events"]}])

        response = self._call(canvas_id, provider="mcp:mcp.example.com", tool="list_events", limit=5)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "not_connected"
        assert body["connect_path"] == "/settings/mcp-servers"

    def test_catalog_lists_native_tools_with_the_callers_connection_state(self):
        response = self.client.get(f"/api/projects/{self.team.id}/canvases/connectors/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        github = next(entry for entry in response.json()["connectors"] if entry["provider"] == "github")
        assert github["connected"] is False
        assert github["kind"] == "native"
        assert [tool["name"] for tool in github["tools"]] == [
            "get_file_contents",
            "list_pull_requests",
            "search_issues",
        ]
        pulls = next(tool for tool in github["tools"] if tool["name"] == "list_pull_requests")
        assert pulls["is_read_only"] is True
        assert pulls["input_schema"]["required"] == ["repository"]
        assert pulls["input_schema"]["properties"]["state"]["enum"] == ["open", "closed", "all"]

        self._connect_github()
        response = self.client.get(f"/api/projects/{self.team.id}/canvases/connectors/?mcp_hosts=mcp.example.com")
        connectors = {entry["provider"]: entry for entry in response.json()["connectors"]}
        assert connectors["github"]["connected"] is True
        assert connectors["mcp:mcp.example.com"] == {
            "provider": "mcp:mcp.example.com",
            "display_name": "mcp.example.com",
            "kind": "mcp",
            "connected": False,
            "connect_path": "/settings/mcp-servers",
            "tools": [],
        }

    @parameterized.expand([("canvas_only", ["canvas:write"], 403), ("user_scope", ["canvas:write", "user:read"], 200)])
    @patch("products.canvas.backend.connectors.UserGitHubIntegration.api_request", return_value=_github_response())
    def test_scoped_keys_need_personal_integration_access(self, _name, scopes, expected_status, mock_request):
        canvas_id = self._connectors_canvas()
        self._connect_github()
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="canvas-connectors", user=self.user, secure_value=hash_key_value(raw_key), scopes=scopes
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        response = self._call(canvas_id)
        assert response.status_code == expected_status
        assert mock_request.called is (expected_status == 200)

    @parameterized.expand(
        [
            ("list_pull_requests", [_GITHUB_PR]),
            ("search_issues", {"items": [_GITHUB_PR]}),
            ("get_file_contents", {"encoding": "base64", "content": "aGk="}),
        ]
    )
    @patch("products.canvas.backend.connectors.UserGitHubIntegration.api_request")
    def test_retries_another_viewer_connection_when_the_first_cannot_read(self, tool, body, mock_request):
        canvas_id = self._connectors_canvas([{"provider": "github", "tools": [tool]}])
        self._connect_github()
        UserIntegration.objects.create(
            user=self.user, kind="github", integration_id="67890", config={"account": {"name": "example"}}
        )
        mock_request.side_effect = [_github_response(404), _github_response(payload=body)]
        response = self._call(canvas_id, tool=tool, repository="example/app", query="bug", file_path="README.md")
        assert response.json()["status"] == "ok"
        assert mock_request.call_count == 2

    @patch("products.canvas.backend.presentation.views.call_connector_tool")
    def test_existing_connector_versions_cannot_read_with_shared_state(self, mock_call):
        canvas_id = self._connectors_canvas()
        canvas = Canvas.objects.for_team(self.team.id).get(id=canvas_id)
        version = canvas.current_source_version
        assert version is not None
        assert version.capabilities is not None
        version.capabilities["posthog"]["state"] = ["shared"]
        version.save(update_fields=["capabilities"])
        assert self._call(canvas_id).status_code == 403
        state_response = self.client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/state/set/",
            {"key": "result", "scope": "shared", "value": "private"},
            format="json",
        )
        assert state_response.status_code == 403
        mock_call.assert_not_called()


class TestConnectorResultBounds(SimpleTestCase):
    @parameterized.expand([("unicode", "😀"), ("escape", "\\"), ("quotes", '"'), ("control", "\n")])
    def test_preview_including_json_envelope_stays_within_byte_limit(self, _name: str, value: str) -> None:
        result, truncated = _bounded({"data": value * MAX_RESULT_BYTES})
        assert truncated
        assert len(json.dumps(result).encode("utf-8")) <= MAX_RESULT_BYTES
