import json
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import serializers, status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user_integration import UserIntegration
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.canvas.backend.connectors import (
    MAX_RESULT_BYTES,
    NATIVE_CONNECTORS,
    ConnectorToolError,
    _bounded,
    _native_field_schema,
)
from products.canvas.backend.models import Canvas
from products.canvas.backend.tests.test_canvas_api import CanvasAPIBaseTest
from products.mcp_store.backend.models import MCPServerInstallation, MCPServerInstallationTool
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
    response.links = {}
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

        sandbox_client = self._sandbox_client(task.id)
        response = sandbox_client.post(
            f"/api/projects/{self.team.id}/canvases/{canvas_id}/connectors/call/",
            {"provider": "github", "tool": "list_pull_requests", "arguments": {"repository": "app"}},
            format="json",
            HTTP_X_POSTHOG_TASK_ID=str(task.id),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

        self._connect_github()
        with (
            patch("products.canvas.backend.connectors._viewer_integration") as lookup,
            patch("products.canvas.backend.connectors.mcp_store_facade.member_server_hosts") as hosts,
            patch("products.canvas.backend.connectors.mcp_store_facade.member_server_tools") as tools,
        ):
            catalog = sandbox_client.get(
                f"/api/projects/{self.team.id}/canvases/connectors/?mcp_hosts=mcp.example.com",
                HTTP_X_POSTHOG_TASK_ID=str(task.id),
            )
            assert catalog.status_code == status.HTTP_200_OK, catalog.json()
            assert [provider["provider"] for provider in catalog.json()["connectors"]] == ["github"]
            assert catalog.json()["connectors"][0]["connected"] is None
            assert "search_pull_requests" in [tool["name"] for tool in catalog.json()["connectors"][0]["tools"]]
            lookup.assert_not_called()
            hosts.assert_not_called()
            tools.assert_not_called()

    @patch("products.canvas.backend.connectors.UserGitHubIntegration.api_request")
    def test_author_me_uses_each_viewers_identity(self, request: MagicMock) -> None:
        canvas_id = self._connectors_canvas([{"provider": "github", "tools": ["search_pull_requests"]}])
        request.return_value = _github_response(payload={"items": [], "total_count": 0, "incomplete_results": False})
        first = self._connect_github()
        first.config["github_user"] = {"login": "octocat"}
        first.save()
        assert (
            self._call(canvas_id, tool="search_pull_requests", repository="example/app", author="me").json()["status"]
            == "ok"
        )
        assert "author:octocat" in request.call_args.kwargs["params"]["q"]

        other_user = self._create_user("canvas-viewer@example.com")
        self.client.force_login(other_user)
        assert (
            self._call(canvas_id, tool="search_pull_requests", repository="example/app", author="me").json()["status"]
            == "not_connected"
        )
        assert request.call_count == 1
        UserIntegration.objects.create(
            user=other_user,
            kind="github",
            integration_id="67890",
            config={"github_user": {"login": "viewer-two"}},
        )
        assert (
            self._call(canvas_id, tool="search_pull_requests", repository="example/app", author="me").json()["status"]
            == "ok"
        )
        assert "author:viewer-two" in request.call_args.kwargs["params"]["q"]

    @patch("products.canvas.backend.connectors.UserGitHubIntegration.get_pull_request_snapshot")
    @patch("products.canvas.backend.connectors.UserGitHubIntegration.api_request", return_value=_github_response())
    def test_failed_status_read_does_not_remove_listed_pr(self, request: MagicMock, snapshot: MagicMock) -> None:
        canvas_id = self._connectors_canvas(
            [{"provider": "github", "tools": ["list_pull_requests", "get_pull_request_snapshot"]}]
        )
        self._connect_github()
        snapshot.return_value = {"success": False, "error": "Permission denied"}
        listed = self._call(canvas_id, repository="example/app").json()
        assert listed["status"] == "ok"
        assert listed["result"]["pull_requests"][0]["number"] == 7
        failed = self._call(canvas_id, tool="get_pull_request_snapshot", repository="example/app", pr_number=7).json()
        assert failed["status"] == "upstream_error"
        assert failed["result"] is None
        assert request.call_count == 1

    def test_mcp_provider_without_a_connection_points_at_the_mcp_store(self):
        canvas_id = self._connectors_canvas([{"provider": "mcp:mcp.example.com", "tools": ["list_events"]}])

        response = self._call(canvas_id, provider="mcp:mcp.example.com", tool="list_events", limit=5)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "not_connected"
        assert body["connect_path"] == "/settings/mcp-servers"

    @patch("products.mcp_store.backend.facade.api.call_upstream_tool", return_value={"content": []})
    def test_mcp_call_requires_a_single_use_token_for_the_exact_arguments(self, upstream: MagicMock) -> None:
        canvas_id = self._connectors_canvas([{"provider": "mcp:calendar.example.com", "tools": ["list_events"]}])
        installation = MCPServerInstallation.objects.create(
            team=self.team,
            user=self.user,
            url="https://calendar.example.com/mcp",
            auth_type="api_key",
            sensitive_configuration={"api_key": "test-only-key"},
        )
        MCPServerInstallationTool.objects.create(
            installation=installation,
            tool_name="list_events",
            approval_state="needs_approval",
            annotations={"readOnlyHint": True},
            last_seen_at=timezone.now(),
        )
        url = f"/api/projects/{self.team.id}/canvases/{canvas_id}/connectors/call/"
        payload = {"provider": "mcp:calendar.example.com", "tool": "list_events", "arguments": {"limit": 5}}
        pending = self.client.post(url, {**payload, "approved": True}, format="json")
        assert pending.status_code == 200
        assert pending.json()["status"] == "needs_approval"
        token = pending.json()["approval_token"]
        assert token
        upstream.assert_not_called()
        changed = self.client.post(url, {**payload, "arguments": {"limit": 10}, "approval_token": token}, format="json")
        assert changed.json()["status"] == "blocked"
        upstream.assert_not_called()
        allowed = self.client.post(url, {**payload, "approval_token": token}, format="json")
        assert allowed.json()["status"] == "ok"
        assert allowed.json()["approval_token"] is None
        replay = self.client.post(url, {**payload, "approval_token": token}, format="json")
        assert replay.json()["status"] == "blocked"
        assert upstream.call_count == 1

    def test_catalog_lists_native_tools_with_the_callers_connection_state(self):
        response = self.client.get(f"/api/projects/{self.team.id}/canvases/connectors/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        github = next(entry for entry in response.json()["connectors"] if entry["provider"] == "github")
        assert github["connected"] is False
        assert github["kind"] == "native"
        assert [tool["name"] for tool in github["tools"]] == [
            "get_file_contents",
            "get_pull_request_checks",
            "get_pull_request_snapshot",
            "list_pull_requests",
            "search_issues",
            "search_pull_requests",
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


class TestGitHubReadTools(SimpleTestCase):
    def setUp(self) -> None:
        client_patch = patch("products.canvas.backend.connectors._github_client")
        self.github = client_patch.start().return_value
        self.addCleanup(client_patch.stop)

    def execute(self, tool_name: str, **arguments: Any) -> dict[str, Any]:
        tool = NATIVE_CONNECTORS["github"].tools[tool_name]
        payload = tool.payload_serializer(data={"repository": "example/app", **arguments})
        payload.is_valid(raise_exception=True)
        return tool.execute(MagicMock(), payload.validated_data)

    def test_author_search_filters_upstream_before_pagination(self) -> None:
        self.github.github_login = "octocat"
        self.github.api_request.return_value = _github_response(
            payload={"items": [_GITHUB_PR], "total_count": 3, "incomplete_results": False}
        )
        result = self.execute("search_pull_requests", author="me", page=2, per_page=1)
        assert self.github.api_request.call_args.kwargs["params"] == {
            "q": "repo:example/app is:pr is:open author:octocat",
            "page": 2,
            "per_page": 1,
            "sort": "created",
            "order": "desc",
        }
        assert self.github.api_request.call_args.args[1] == "/search/issues"
        assert result["pull_requests"][0]["author"] == "octocat"
        assert result["next_page"] == 3
        assert result["has_next_page"] is True
        assert result["incomplete_results"] is False
        assert self.github.api_request.call_count == 1

    def test_me_requires_connected_user_identity(self) -> None:
        self.github.github_login = None
        with self.assertRaisesMessage(ConnectorToolError, "identity"):
            self.execute("search_pull_requests", author="me")
        self.github.api_request.assert_not_called()

    @parameterized.expand([(False, 0, False), (True, 0, False), (False, 1001, True)])
    def test_search_reports_incomplete_results_and_search_limit(
        self, incomplete: bool, total: int, limited: bool
    ) -> None:
        self.github.api_request.return_value = _github_response(
            payload={"items": [], "total_count": total, "incomplete_results": incomplete}
        )
        result = self.execute("search_pull_requests", page=10, per_page=100)
        assert result["next_page"] is None
        assert result["has_next_page"] is False
        assert result["incomplete_results"] is incomplete
        assert result["search_limit_reached"] is limited

    def test_list_pagination_preserves_existing_pr_shape(self) -> None:
        response = _github_response()
        response.links = {"next": {"url": "https://api.github.com/repos/example/app/pulls?page=3"}}
        self.github.api_request.return_value = response
        result = self.execute("list_pull_requests", page=2, per_page=1)
        assert result["next_page"] == 3
        assert result["pull_requests"][0]["state"] == "open"
        assert result["pull_requests"][0]["draft"] is False
        assert self.github.api_request.call_args.kwargs["params"]["page"] == 2

    @parameterized.expand([("get_pull_request_snapshot",), ("get_pull_request_checks",)])
    def test_status_helper_failures_are_not_successful_data(self, tool: str) -> None:
        getattr(self.github, tool).return_value = {"success": False, "error": "Permission denied"}
        with self.assertRaisesMessage(ConnectorToolError, "Permission denied"):
            self.execute(tool, pr_number=7)

    def test_snapshot_preserves_unknown_review_and_head_sha(self) -> None:
        self.github.get_pull_request_snapshot.return_value = {
            "success": True,
            "state": "draft",
            "review_decision": None,
            "ci_status": "pending",
            "head_sha": "abc123",
        }
        result = self.execute("get_pull_request_snapshot", pr_number=7)
        assert result["review_decision"] is None
        assert result["head_sha"] == "abc123"
        self.github.get_pull_request_snapshot.assert_called_once_with("https://github.com/example/app/pull/7")

    def test_no_checks_is_a_successful_empty_list(self) -> None:
        self.github.get_pull_request_checks.return_value = {"success": True, "checks": []}
        assert self.execute("get_pull_request_checks", pr_number=7) == {"checks": []}
        self.github.get_pull_request_checks.assert_called_once_with("example/app", 7)

    @parameterized.expand(
        [
            ({"author": "octocat repo:other/private"},),
            ({"page": 0},),
            ({"page": 11, "per_page": 100},),
            ({"per_page": 101},),
            ({"state": "invalid"},),
            ({"repository": "../private"},),
        ]
    )
    def test_search_rejects_unsafe_or_out_of_range_arguments(self, arguments: dict[str, Any]) -> None:
        with self.assertRaises(serializers.ValidationError):
            self.execute("search_pull_requests", **arguments)
        self.github.api_request.assert_not_called()

    def test_search_text_cannot_override_repository_or_pr_filters(self) -> None:
        self.github.api_request.return_value = _github_response(
            payload={"items": [], "total_count": 0, "incomplete_results": False}
        )
        self.execute("search_pull_requests", query='" is:issue repo:other/private', draft=True, state="all")
        assert self.github.api_request.call_args.kwargs["params"]["q"] == (
            'repo:example/app is:pr draft:true "  is:issue repo:other/private"'
        )

    def test_catalog_schema_describes_nested_fields_and_constraints(self) -> None:
        class Reference(serializers.Serializer):
            number = serializers.IntegerField(min_value=1, max_value=100)
            branch = serializers.RegexField(r"^[a-z]+$", max_length=20, allow_null=True, default=None)

        class Payload(serializers.Serializer):
            references = Reference(many=True)
            labels = serializers.ListField(child=serializers.CharField(max_length=10), max_length=5)
            options = serializers.DictField(child=serializers.BooleanField())

        schema = _native_field_schema(Payload())
        reference = schema["properties"]["references"]["items"]
        assert reference["required"] == ["number"]
        assert reference["properties"]["number"]["minimum"] == 1
        assert reference["properties"]["number"]["maximum"] == 100
        assert reference["properties"]["branch"]["type"] == ["string", "null"]
        assert reference["properties"]["branch"]["default"] is None
        assert reference["properties"]["branch"]["pattern"] == "^[a-z]+$"
        assert schema["properties"]["labels"]["maxItems"] == 5
        assert schema["properties"]["labels"]["items"]["maxLength"] == 10
        assert schema["properties"]["options"]["additionalProperties"]["type"] == "boolean"
