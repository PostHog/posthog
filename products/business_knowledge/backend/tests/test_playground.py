from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils.timezone import now

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
        assert self.client.get(self.url).json()["results"] == []
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

        untitled = self._create_chat()
        second = self._create_chat()
        parallel = self.client.post(
            f"{self.url}{second['id']}/ask/", {"question": "Where is the policy?"}, format="json"
        )
        assert parallel.status_code == status.HTTP_201_CREATED, parallel.content
        assert Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).count() == 2

        listed = {chat["id"]: chat["has_open_turn"] for chat in self.client.get(self.url).json()["results"]}
        assert listed == {first["id"]: True, second["id"]: True}
        assert untitled["id"] not in listed

        TaskRun.objects.filter(task_id=started.json()["turns"][0]["task_id"]).update(
            status=TaskRun.Status.COMPLETED, output={"reply": "Yes.", "sources": []}
        )
        listed = {chat["id"]: chat["has_open_turn"] for chat in self.client.get(self.url).json()["results"]}
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
        assert listed.json()["results"][0]["id"] == chat["id"]
        still_readable = self.client.get(f"{self.url}{chat['id']}/")
        assert still_readable.status_code == status.HTTP_200_OK
        blocked = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "Another question"}, format="json")
        assert blocked.status_code == status.HTTP_403_FORBIDDEN

    def test_list_pages_by_most_recently_updated(self, _ff, _workflow) -> None:
        chats = [self._create_chat() for _ in range(3)]
        PlaygroundChat.objects.unscoped().filter(id__in=[chat["id"] for chat in chats]).update(title="Refunds")
        PlaygroundChat.objects.unscoped().filter(id=chats[0]["id"]).update(title="Latest", updated_at=now())

        first_page = self.client.get(self.url, {"limit": 2}).json()
        second_page = self.client.get(first_page["next"]).json()

        assert first_page["count"] == 3
        assert first_page["results"][0]["id"] == chats[0]["id"]
        listed = [chat["id"] for chat in first_page["results"] + second_page["results"]]
        assert sorted(listed) == sorted(chat["id"] for chat in chats)
        assert second_page["next"] is None

        PlaygroundChat.objects.unscoped().bulk_create(
            [PlaygroundChat(team=self.team, created_by=self.user, title="Another chat") for _ in range(101)]
        )
        capped_page = self.client.get(self.url, {"limit": 1000}).json()
        assert capped_page["count"] == 104
        assert len(capped_page["results"]) == 100
        assert capped_page["next"] is not None

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

    def test_blank_ask_is_rejected(self, _ff, _workflow) -> None:
        chat = self._create_chat()
        response = self.client.post(f"{self.url}{chat['id']}/ask/", {"question": "   "}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Task.objects.filter(origin_product=Task.OriginProduct.BUSINESS_KNOWLEDGE).exists()
