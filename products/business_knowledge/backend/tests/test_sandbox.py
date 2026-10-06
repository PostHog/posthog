import json
import uuid
import threading

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import close_old_connections
from django.test import SimpleTestCase, TransactionTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.business_knowledge.backend.api.sandbox import BusinessKnowledgeSandboxViewSet
from products.business_knowledge.backend.api.serializers import SandboxQuestionSerializer, SandboxSearchSerializer
from products.business_knowledge.backend.logic import KnowledgeSearchResult
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource, SafetyVerdict
from products.business_knowledge.backend.sandbox import (
    BK_REPO_FILE_TOOL,
    BK_REPO_SEARCH_TOOL,
    BK_SEARCH_TOOL,
    BK_WINDOW_TOOL,
    DOCS_SEARCH_TOOL,
    SandboxAnswer,
    build_sandbox_prompt,
    format_always_on_context,
    parse_sandbox_log,
)
from products.tasks.backend.models import SandboxEnvironment, Task, TaskRun

WORKFLOW = "products.tasks.backend.temporal.client.execute_task_processing_workflow"


def _update_line(tool_call_id: str, raw_input: dict | None, *, session_update: str = "tool_call_update") -> str:
    update: dict = {"sessionUpdate": session_update, "toolCallId": tool_call_id}
    if raw_input is not None:
        update["rawInput"] = raw_input
    return json.dumps({"notification": {"method": "session/update", "params": {"update": update}}})


class TestSandboxQuestionSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("blank", ""),
            ("whitespace", "   "),
        ]
    )
    def test_rejects_blank_questions(self, _name: str, question: str) -> None:
        serializer = SandboxQuestionSerializer(data={"question": question})
        assert not serializer.is_valid()
        assert "question" in serializer.errors

    def test_trims_and_caps_length(self) -> None:
        serializer = SandboxQuestionSerializer(data={"question": "  refunds  "})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["question"] == "refunds"
        assert not SandboxQuestionSerializer(data={"question": "x" * 4001}).is_valid()


class TestSandboxLogParser(SimpleTestCase):
    def test_waits_for_populated_input_and_dedupes(self) -> None:
        log = "\n".join(
            [
                _update_line("call-1", {}),
                _update_line("call-1", None),
                _update_line(
                    "call-1",
                    {"command": f"call {BK_SEARCH_TOOL} " + json.dumps({"query": "refunds"})},
                ),
                _update_line(
                    "call-1",
                    {"command": f"call {BK_SEARCH_TOOL} " + json.dumps({"query": "again"})},
                ),
            ]
        )
        activity = parse_sandbox_log(log)
        assert activity.docs_search_called is False
        assert len(activity.searches) == 1
        assert activity.searches[0].tool == BK_SEARCH_TOOL
        assert "refunds" in activity.searches[0].tool_input

    def test_recognizes_repository_tools(self) -> None:
        log = "\n".join(
            [
                _update_line(
                    "repo-search",
                    {"command": f"call {BK_REPO_SEARCH_TOOL} " + json.dumps({"query": "billing"})},
                ),
                _update_line(
                    "repo-file",
                    {
                        "command": f"call {BK_REPO_FILE_TOOL} "
                        + json.dumps({"repo": "acme/billing", "path": "src/a.py"})
                    },
                ),
            ]
        )
        activity = parse_sandbox_log(log)
        assert [search.tool for search in activity.searches] == [BK_REPO_SEARCH_TOOL, BK_REPO_FILE_TOOL]
        for tool in (BK_REPO_SEARCH_TOOL, BK_REPO_FILE_TOOL):
            assert SandboxSearchSerializer(data={"tool": tool, "input": "call"}).is_valid()

    def test_prompt_names_repository_tools_only_when_enabled(self) -> None:
        without = build_sandbox_prompt("Can I get a refund?", "")
        assert BK_REPO_SEARCH_TOOL not in without
        with_repos = build_sandbox_prompt("Can I get a refund?", "", repo_tools=True)
        assert BK_REPO_SEARCH_TOOL in with_repos
        assert BK_REPO_FILE_TOOL in with_repos

    def test_accepts_direct_tool_names_and_exact_docs_search(self) -> None:
        direct = json.dumps(
            {
                "notification": {
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": "direct",
                            "title": BK_WINDOW_TOOL,
                            "rawInput": {"query": "refunds"},
                        }
                    },
                }
            }
        )
        log = "\n".join(
            [
                json.dumps(
                    {
                        "notification": {
                            "method": "session/update",
                            "params": {
                                "update": {
                                    "sessionUpdate": "agent_message_chunk",
                                    "content": {"text": f"call {DOCS_SEARCH_TOOL} and {BK_SEARCH_TOOL}"},
                                }
                            },
                        }
                    }
                ),
                direct,
                _update_line("docs", {"command": f"call {DOCS_SEARCH_TOOL} {{}}"}),
                _update_line("not-docs", {"command": f"echo call {DOCS_SEARCH_TOOL} later"}),
            ]
        )
        activity = parse_sandbox_log(log)
        assert [search.tool for search in activity.searches] == [BK_WINDOW_TOOL]
        assert activity.docs_search_called is True

    def test_learned_chunks_are_labeled(self) -> None:
        text = format_always_on_context(
            [
                KnowledgeSearchResult(
                    chunk_id=uuid.uuid4(),
                    source_id=uuid.uuid4(),
                    source_name="Refunds",
                    source_type="text",
                    document_id=uuid.uuid4(),
                    document_title="Refunds",
                    heading_path="",
                    ordinal=0,
                    content="Refunds need approval.",
                    is_generated=True,
                )
            ]
        )
        assert "[learned from support] Refunds need approval." in text
        assert format_always_on_context([]) == ""


class TestSandboxScopes(SimpleTestCase):
    @parameterized.expand(
        [("create", "POST", "business_knowledge:write"), ("retrieve", "GET", "business_knowledge:read")]
    )
    def test_required_scopes(self, action: str, method: str, scope: str) -> None:
        view = BusinessKnowledgeSandboxViewSet()
        view.action = action
        assert view.dangerously_get_required_scopes(APIRequestFactory().generic(method, "/"), view) == [scope]


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch(WORKFLOW)
class TestSandboxAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.url = f"/api/projects/{self.team.id}/business_knowledge/sandbox/"

    def _auth_with_pak(self, scopes: list[str]) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    def test_post_locks_the_sandbox_to_business_knowledge(self, _ff, _workflow) -> None:
        source = KnowledgeSource.objects.unscoped().create(
            team_id=self.team.id,
            name="Refunds",
            source_type="text",
            status="ready",
            always_include=True,
            is_generated=True,
        )
        document = KnowledgeDocument.objects.unscoped().create(
            team_id=self.team.id,
            source=source,
            stable_id=str(uuid.uuid4()),
            title="Refunds",
            content="Refunds need approval.",
            content_hash="abc",
            safety_verdict=SafetyVerdict.SAFE,
        )
        KnowledgeChunk.objects.unscoped().create(
            id=uuid.uuid4(),
            team_id=self.team.id,
            source=source,
            document=document,
            ordinal=0,
            content="Refunds need approval.",
            char_count=22,
        )

        response = self.client.post(self.url, {"question": "  Can I get a refund?  "}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        task = Task.objects.get(id=body["task_id"])
        run = TaskRun.objects.get(id=body["run_id"])
        assert task.origin_product == Task.OriginProduct.BUSINESS_KNOWLEDGE
        assert task.internal is True
        assert task.repository is None
        assert task.created_by_id == self.user.id
        assert run.state["pending_dispatch"]["posthog_mcp_scopes"] == [
            "business_knowledge:read",
            "user:read",
            "project:read",
        ]
        assert {
            DOCS_SEARCH_TOOL,
            "user-get",
            "project-get",
            "mcp-connections-list",
            "mcp-connection-tools-list",
            "tasks-runs-session-logs-retrieve",
            "tasks-artifacts-list",
        } <= set(run.state["mcp_exclude_tools"])
        assert run.state["config_snapshot"]["connectors"]["mcp_installation_ids"] == []
        assert run.state["model"] == "claude-sonnet-5"
        assert run.state["runtime_adapter"] == "claude"
        assert "initial_permission_mode" not in run.state
        assert "pending_user_message" not in run.state
        assert run.imported_mcp_servers is None
        assert BK_SEARCH_TOOL in task.description
        assert BK_WINDOW_TOOL in task.description
        assert f"{DOCS_SEARCH_TOOL} is unavailable" in task.description
        assert "<question>" in task.description
        assert "Can I get a refund?" in task.description
        assert "[learned from support] Refunds need approval." in task.description
        schema = SandboxAnswer.model_json_schema()
        assert task.json_schema is not None
        assert task.json_schema["properties"]["reply"]["type"] == schema["properties"]["reply"]["type"]
        env = SandboxEnvironment.objects.get(team_id=self.team.id, name="BUSINESS_KNOWLEDGE_SANDBOX")
        assert env.internal is True
        assert env.network_access_level == SandboxEnvironment.NetworkAccessLevel.CUSTOM
        assert env.allowed_domains == []
        assert env.include_default_domains is False

        running = self.client.get(f"{self.url}{task.id}/")
        assert running.status_code == status.HTTP_200_OK
        assert running.json()["status"] == "running"

        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        still_readable = self.client.get(f"{self.url}{task.id}/")
        assert still_readable.status_code == status.HTTP_200_OK
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        blocked = self.client.post(self.url, {"question": "Another question"}, format="json")
        assert blocked.status_code == status.HTTP_409_CONFLICT
        assert Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).count() == 1

        Task.objects.filter(id=task.id).update(deleted=True)
        still_blocked = self.client.post(self.url, {"question": "Another question"}, format="json")
        assert still_blocked.status_code == status.HTTP_409_CONFLICT

    @parameterized.expand(
        [
            ("read", "business_knowledge:read", status.HTTP_403_FORBIDDEN),
            ("write", "business_knowledge:write", status.HTTP_201_CREATED),
        ]
    )
    def test_asking_needs_write_scope(self, _ff, _workflow, _name: str, scope: str, expected: int) -> None:
        self._auth_with_pak([scope])
        response = self.client.post(self.url, {"question": "Where is the refund policy?"}, format="json")
        assert response.status_code == expected, response.content

    @parameterized.expand([("declined", False), ("undecided", None)])
    def test_ai_data_processing_required_to_ask(self, _ff, _workflow, _name: str, approval: bool | None) -> None:
        self.organization.is_ai_data_processing_approved = approval
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        response = self.client.post(self.url, {"question": "Can I get a refund?"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI data processing" in response.json()["detail"]
        assert not Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).exists()

    def test_other_owner_and_team_are_hidden(self, _ff, _workflow) -> None:
        started = self.client.post(self.url, {"question": "Can I get a refund?"}, format="json")
        task_id = started.json()["task_id"]
        other = User.objects.create_user(email="other@example.com", password="password", first_name="Other")
        OrganizationMembership.objects.create(user=other, organization=self.organization)
        self.client.force_login(other)
        assert self.client.get(f"{self.url}{task_id}/").status_code == status.HTTP_404_NOT_FOUND

        self.client.force_login(self.user)
        tasks_url = f"/api/projects/{self.team.id}/tasks/"
        assert self.client.get(f"{tasks_url}{task_id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(f"{tasks_url}{task_id}/runs/").status_code == status.HTTP_404_NOT_FOUND
        listed = self.client.get(tasks_url, {"internal": "true"}).json()["results"]
        assert task_id not in {task["id"] for task in listed}
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        other_url = f"/api/projects/{other_team.id}/business_knowledge/sandbox/{task_id}/"
        assert self.client.get(other_url).status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            (
                "completed",
                TaskRun.Status.COMPLETED,
                {"reply": "Yes, within 30 days.", "sources": []},
                "completed",
                None,
            ),
            ("failed", TaskRun.Status.FAILED, None, "failed", "sandbox exploded"),
            ("cancelled", TaskRun.Status.CANCELLED, None, "cancelled", "stopped"),
            ("bad_output", TaskRun.Status.COMPLETED, {"reply": ""}, "failed", "expected shape"),
        ]
    )
    def test_terminal_runs(
        self,
        _ff,
        _workflow,
        _name: str,
        run_status: str,
        output: dict | None,
        expected_status: str,
        error_snippet: str | None,
    ) -> None:
        started = self.client.post(self.url, {"question": "Can I get a refund?"}, format="json")
        run = TaskRun.objects.get(id=started.json()["run_id"])
        run.status = run_status
        run.output = output
        run.error_message = error_snippet
        run.save(update_fields=["status", "output", "error_message"])

        body = self.client.get(f"{self.url}{started.json()['task_id']}/").json()
        assert body["status"] == expected_status
        if expected_status == "completed":
            assert body["reply"] == "Yes, within 30 days."
            assert body["error"] is None
        else:
            assert body["reply"] is None
            assert error_snippet in body["error"]

    def test_get_reports_an_exact_docs_search_call(self, _ff, _workflow) -> None:
        started = self.client.post(self.url, {"question": "Can I get a refund?"}, format="json")
        log = "\n".join(
            [
                f"prompt mentions call {DOCS_SEARCH_TOOL}",
                _update_line("search", {"command": f"call {BK_SEARCH_TOOL} " + json.dumps({"query": "refunds"})}),
                _update_line("docs", {"command": f"call {DOCS_SEARCH_TOOL} {{}}"}),
            ]
        )
        with patch(
            "products.business_knowledge.backend.sandbox.tasks_facade.read_task_run_logs",
            return_value=log,
        ):
            body = self.client.get(f"{self.url}{started.json()['task_id']}/").json()
        assert body["docs_search_called"] is True
        assert body["searches"] == [
            {"tool": BK_SEARCH_TOOL, "input": f"call {BK_SEARCH_TOOL} " + json.dumps({"query": "refunds"})}
        ]

    def test_finished_run_reads_its_log_once(self, _ff, _workflow) -> None:
        started = self.client.post(self.url, {"question": "Can I get a refund?"}, format="json")
        TaskRun.objects.filter(id=started.json()["run_id"]).update(
            status=TaskRun.Status.COMPLETED, output={"reply": "Yes, within 30 days.", "sources": []}
        )
        search = _update_line("search", {"command": f"call {BK_SEARCH_TOOL} " + json.dumps({"query": "refunds"})})
        with patch(
            "products.business_knowledge.backend.sandbox.tasks_facade.read_task_run_logs",
            return_value=search,
        ) as read_logs:
            first = self.client.get(f"{self.url}{started.json()['task_id']}/").json()
            second = self.client.get(f"{self.url}{started.json()['task_id']}/").json()
        assert read_logs.call_count == 1
        assert first["searches"] == second["searches"]
        assert len(second["searches"]) == 1

    def test_blank_question_is_rejected(self, _ff, _workflow) -> None:
        response = self.client.post(self.url, {"question": "   "}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestSandboxAdmissionRace(TransactionTestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Sandbox org", is_ai_data_processing_approved=True)
        self.user = User.objects.create_user(email="owner@example.com", password="password", first_name="Owner")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Sandbox"
        )
        self.url = f"/api/projects/{self.team.id}/business_knowledge/sandbox/"

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch(WORKFLOW)
    def test_concurrent_posts_create_one_task(self, _workflow, _ff) -> None:
        barrier = threading.Barrier(2)
        statuses: list[int] = []

        def ask() -> None:
            close_old_connections()
            client = APIClient()
            client.force_login(self.user)
            try:
                barrier.wait(timeout=10)
                response = client.post(self.url, {"question": "Can I get a refund?"}, format="json")
                statuses.append(response.status_code)
            finally:
                close_old_connections()

        threads = [threading.Thread(target=ask), threading.Thread(target=ask)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert sorted(statuses) == [status.HTTP_201_CREATED, status.HTTP_409_CONFLICT]
        assert Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).count() == 1
