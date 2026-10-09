from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.business_knowledge.backend.api.playground import BusinessKnowledgePlaygroundChatViewSet
from products.business_knowledge.backend.models import PlaygroundChat, PlaygroundTurn
from products.business_knowledge.backend.sandbox import MAX_OPEN_RUNS_PER_OWNER
from products.tasks.backend.models import Task, TaskRun

WORKFLOW = "products.tasks.backend.temporal.client.execute_task_processing_workflow"


class TestPlaygroundChatScopes(SimpleTestCase):
    @parameterized.expand(
        [
            ("list", "GET", "business_knowledge:read"),
            ("retrieve", "GET", "business_knowledge:read"),
            ("create", "POST", "business_knowledge:write"),
            ("destroy", "DELETE", "business_knowledge:write"),
            ("ask", "POST", "business_knowledge:write"),
        ]
    )
    def test_required_scopes(self, action: str, method: str, scope: str) -> None:
        view = BusinessKnowledgePlaygroundChatViewSet()
        view.action = action
        assert view.dangerously_get_required_scopes(APIRequestFactory().generic(method, "/"), view) == [scope]


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch(WORKFLOW)
class TestPlaygroundChatAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.url = f"/api/projects/{self.team.id}/business_knowledge/playground/chats/"

    def _create_chat(self) -> dict:
        response = self.client.post(self.url, {}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        return response.json()

    def test_owner_isolation(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        chat_url = f"{self.url}{chat['id']}/"
        other = User.objects.create_user(email="other@example.com", password="password", first_name="Other")
        OrganizationMembership.objects.create(user=other, organization=self.organization)
        self.client.force_login(other)
        assert self.client.get(self.url).json() == []
        assert self.client.get(chat_url).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.delete(chat_url).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.post(f"{chat_url}ask/", {"question": "Can I get a refund?"}, format="json").status_code == (
            status.HTTP_404_NOT_FOUND
        )

        self.client.force_login(self.user)
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        other_url = f"/api/projects/{other_team.id}/business_knowledge/playground/chats/{chat['id']}/"
        assert self.client.get(other_url).status_code == status.HTTP_404_NOT_FOUND
        assert PlaygroundChat.objects.unscoped().filter(id=chat["id"]).exists()

    def test_one_open_answer_per_chat_while_other_chats_run(self, _ff, _workflow) -> None:
        first = self._create_chat()
        started = self.client.post(f"{self.url}{first['id']}/ask/", {"question": "Can I get a refund?"}, format="json")
        assert started.status_code == status.HTTP_201_CREATED, started.content
        assert started.json()["has_open_turn"] is True

        blocked = self.client.post(f"{self.url}{first['id']}/ask/", {"question": "And after 30 days?"}, format="json")
        assert blocked.status_code == status.HTTP_409_CONFLICT
        assert PlaygroundTurn.objects.unscoped().filter(chat_id=first["id"]).count() == 1
        assert TaskRun.objects.filter(task_id=started.json()["turns"][0]["task_id"]).count() == 1

        untitled = self._create_chat()
        second = self._create_chat()
        parallel = self.client.post(
            f"{self.url}{second['id']}/ask/", {"question": "Where is the policy?"}, format="json"
        )
        assert parallel.status_code == status.HTTP_201_CREATED, parallel.content
        assert Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).count() == 2

        listed = {chat["id"]: chat["has_open_turn"] for chat in self.client.get(self.url).json()}
        assert listed == {first["id"]: True, second["id"]: True}
        assert untitled["id"] not in listed

        TaskRun.objects.filter(task_id=started.json()["turns"][0]["task_id"]).update(
            status=TaskRun.Status.COMPLETED, output={"reply": "Yes.", "sources": []}
        )
        listed = {chat["id"]: chat["has_open_turn"] for chat in self.client.get(self.url).json()}
        assert listed == {first["id"]: False, second["id"]: True}
        follow_up = self.client.post(f"{self.url}{first['id']}/ask/", {"question": "And after 30 days?"}, format="json")
        assert follow_up.status_code == status.HTTP_201_CREATED, follow_up.content

        third = self._create_chat()
        at_cap = self.client.post(f"{self.url}{third['id']}/ask/", {"question": "Who approves?"}, format="json")
        assert at_cap.status_code == status.HTTP_201_CREATED, at_cap.content
        fourth = self._create_chat()
        over_cap = self.client.post(f"{self.url}{fourth['id']}/ask/", {"question": "Who approves?"}, format="json")
        assert over_cap.status_code == status.HTTP_409_CONFLICT
        assert f"{MAX_OPEN_RUNS_PER_OWNER} answers running" in over_cap.json()["detail"]
        assert not PlaygroundTurn.objects.unscoped().filter(chat_id=fourth["id"]).exists()

    def test_reload_reads_the_sandbox_run(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        asked = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "  Can I get a refund?  "}, format="json")
        assert asked.status_code == status.HTTP_201_CREATED, asked.content
        body = asked.json()
        assert body["title"] == "Can I get a refund?"
        turn = body["turns"][0]
        assert turn["question"] == "Can I get a refund?"
        assert turn["run"]["status"] == "running"

        run = TaskRun.objects.get(id=turn["run"]["run_id"])
        run.status = TaskRun.Status.COMPLETED
        run.output = {"reply": "Yes, within 30 days.", "sources": []}
        run.save(update_fields=["status", "output"])

        reloaded = self.client.get(f"{self.url}{chat['id']}/")
        assert reloaded.status_code == status.HTTP_200_OK
        loaded_turn = reloaded.json()["turns"][0]
        assert loaded_turn["run"]["status"] == "completed"
        assert loaded_turn["run"]["reply"] == "Yes, within 30 days."

        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        listed = self.client.get(self.url)
        assert listed.status_code == status.HTTP_200_OK
        assert listed.json()[0]["id"] == chat["id"]
        still_readable = self.client.get(f"{self.url}{chat['id']}/")
        assert still_readable.status_code == status.HTTP_200_OK
        PlaygroundTurn.objects.unscoped().filter(chat_id=chat["id"]).update(run_id=None)
        legacy = self.client.get(f"{self.url}{chat['id']}/")
        assert legacy.status_code == status.HTTP_200_OK
        assert legacy.json()["turns"][0]["run"]["reply"] == "Yes, within 30 days."
        blocked = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "Another question"}, format="json")
        assert blocked.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_keeps_the_sandbox_task(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        asked = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "Can I get a refund?"}, format="json")
        task_id = asked.json()["turns"][0]["task_id"]
        deleted = self.client.delete(f"{self.url}{chat['id']}/")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert not PlaygroundChat.objects.unscoped().filter(id=chat["id"]).exists()
        assert Task.objects.filter(id=task_id).exists()

    def test_turn_insert_failure_rolls_back_the_run(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        with patch(
            "products.business_knowledge.backend.playground.PlaygroundTurn.objects.create",
            side_effect=RuntimeError("insert failed"),
        ):
            response = self.client.post(
                f"{self.url}{chat['id']}/ask/", {"question": "Can I get a refund?"}, format="json"
            )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert not Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).exists()
        assert PlaygroundTurn.objects.unscoped().count() == 0

    def test_follow_up_resumes_the_same_sandbox(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        asked = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "Can I get a refund?"}, format="json")
        assert asked.status_code == status.HTTP_201_CREATED, asked.content
        first_turn = asked.json()["turns"][0]
        first_run = TaskRun.objects.get(id=first_turn["run"]["run_id"])
        first_run.status = TaskRun.Status.COMPLETED
        first_run.output = {"reply": "Yes, within 30 days.", "sources": []}
        first_run.save(update_fields=["status", "output"])
        description = Task.objects.get(id=first_turn["task_id"]).description

        follow_up = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "And after 30 days?"}, format="json")
        assert follow_up.status_code == status.HTTP_201_CREATED, follow_up.content
        body = follow_up.json()
        assert len(body["turns"]) == 2
        assert body["turns"][0]["task_id"] == body["turns"][1]["task_id"] == first_turn["task_id"]
        assert body["turns"][0]["run"]["status"] == "completed"
        assert body["turns"][0]["run"]["reply"] == "Yes, within 30 days."
        assert body["turns"][1]["question"] == "And after 30 days?"
        assert body["turns"][1]["run"]["status"] == "running"
        assert body["turns"][1]["run"]["reply"] is None

        successor = TaskRun.objects.get(id=body["turns"][1]["run"]["run_id"])
        assert successor.id != first_run.id
        assert successor.task_id == first_run.task_id
        assert successor.state["resume_from_run_id"] == str(first_run.id)
        assert successor.state["pending_user_message"] == "And after 30 days?"
        assert successor.state["mcp_exclude_tools"] == first_run.state["mcp_exclude_tools"]
        assert successor.state["config_snapshot"] == first_run.state["config_snapshot"]
        assert successor.state["model"] == first_run.state["model"]
        assert successor.state["runtime_adapter"] == first_run.state["runtime_adapter"]
        assert successor.state.get("sandbox_environment_id") == first_run.state.get("sandbox_environment_id")
        assert (
            successor.state["pending_dispatch"]["posthog_mcp_scopes"]
            == first_run.state["pending_dispatch"]["posthog_mcp_scopes"]
        )
        assert Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).count() == 1
        task = Task.objects.get(id=first_run.task_id)
        assert task.description == description
        assert "And after 30 days?" not in task.description

        reloaded = self.client.get(f"{self.url}{chat['id']}/")
        assert reloaded.status_code == status.HTTP_200_OK
        loaded = reloaded.json()["turns"]
        assert loaded[0]["run"]["reply"] == "Yes, within 30 days."
        assert loaded[0]["run"]["run_id"] == str(first_run.id)
        assert loaded[1]["run"]["run_id"] == str(successor.id)
        assert loaded[1]["run"]["status"] == "running"

    def test_follow_up_resumes_a_later_turn_on_another_task(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        asked = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "Can I get a refund?"}, format="json")
        assert asked.status_code == status.HTTP_201_CREATED, asked.content
        first_task_id = asked.json()["turns"][0]["task_id"]
        TaskRun.objects.filter(task_id=first_task_id).update(
            status=TaskRun.Status.COMPLETED, output={"reply": "Yes, within 30 days.", "sources": []}
        )
        other = self.client.post(
            f"/api/projects/{self.team.id}/business_knowledge/sandbox/",
            {"question": "Where is the policy?"},
            format="json",
        )
        assert other.status_code == status.HTTP_201_CREATED, other.content
        other_task_id = other.json()["task_id"]
        other_run_id = other.json()["run_id"]
        TaskRun.objects.filter(id=other_run_id).update(
            status=TaskRun.Status.COMPLETED, output={"reply": "In the handbook.", "sources": []}
        )
        PlaygroundTurn.objects.unscoped().create(
            team_id=self.team.id,
            chat_id=chat["id"],
            question="Where is the policy?",
            task_id=other_task_id,
            run_id=other_run_id,
            position=1,
        )

        follow_up = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "And after 30 days?"}, format="json")
        assert follow_up.status_code == status.HTTP_201_CREATED, follow_up.content
        body = follow_up.json()
        assert body["turns"][0]["task_id"] == first_task_id
        assert body["turns"][1]["run"]["reply"] == "In the handbook."
        assert body["turns"][2]["task_id"] == other_task_id
        successor = TaskRun.objects.get(id=body["turns"][2]["run"]["run_id"])
        assert str(successor.task_id) == other_task_id
        assert successor.state["resume_from_run_id"] == other_run_id
        assert str(PlaygroundChat.objects.unscoped().get(id=chat["id"]).task_id) == other_task_id

    def test_follow_up_keeps_an_unpinned_earlier_answer(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        asked = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "Can I get a refund?"}, format="json")
        assert asked.status_code == status.HTTP_201_CREATED, asked.content
        first_run_id = asked.json()["turns"][0]["run"]["run_id"]
        TaskRun.objects.filter(id=first_run_id).update(
            status=TaskRun.Status.COMPLETED, output={"reply": "Yes, within 30 days.", "sources": []}
        )
        PlaygroundTurn.objects.unscoped().filter(chat_id=chat["id"]).update(run_id=None)

        follow_up = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "And after 30 days?"}, format="json")
        assert follow_up.status_code == status.HTTP_201_CREATED, follow_up.content
        reloaded = self.client.get(f"{self.url}{chat['id']}/")
        turns = reloaded.json()["turns"]
        assert turns[0]["run"]["run_id"] == first_run_id
        assert turns[0]["run"]["reply"] == "Yes, within 30 days."
        assert turns[1]["run"]["run_id"] != first_run_id
        assert turns[1]["run"]["status"] == "running"

    def test_blank_ask_is_rejected(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        response = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "   "}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).exists()
