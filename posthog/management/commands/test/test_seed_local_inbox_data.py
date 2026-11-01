import json
from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models import Team, User


class TestLocalInboxProductionGuard(SimpleTestCase):
    @parameterized.expand(
        [
            ("production", False, False, None, "http://localhost:8010", "only available in local development"),
            ("cloud", True, True, "US", "http://localhost:8010", "only available in local development"),
            ("remote", True, True, None, "https://example.com", "requires a loopback SITE_URL"),
            ("credentials", True, True, None, "http://demo:demo@localhost:8010", "requires a loopback SITE_URL"),
            ("path", True, True, None, "http://localhost:8010/example", "requires a loopback SITE_URL"),
            ("query", True, True, None, "http://localhost:8010/?example=1", "requires a loopback SITE_URL"),
            ("fragment", True, True, None, "http://localhost:8010/#example", "requires a loopback SITE_URL"),
            ("port", True, True, None, "http://localhost:invalid", "requires a loopback SITE_URL"),
        ]
    )
    def test_refuses_nonlocal_environments_before_accessing_the_database(
        self, _name: str, debug: bool, test: bool, cloud: str | None, site_url: str, message: str
    ) -> None:
        with (
            override_settings(DEBUG=debug, TEST=test, CLOUD_DEPLOYMENT=cloud, SITE_URL=site_url),
            self.assertRaisesMessage(CommandError, message),
        ):
            call_command("seed_local_inbox_data", team_id=1, user_id=1)


@override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None, SITE_URL="http://localhost:8010", OBJECT_STORAGE_ENABLED=True)
class TestSeedLocalInboxData(APIBaseTest):
    def _seed(self, team_id: int, user_id: int) -> dict[str, Any]:
        output = StringIO()
        call_command("seed_local_inbox_data", team_id=team_id, user_id=user_id, json=True, stdout=output)
        return json.loads(output.getvalue())

    def test_repeat_preserves_personal_inbox_and_chat_with_readable_logs(self) -> None:
        storage: dict[str, str] = {}

        def read(path: str, **kwargs: object) -> str | None:
            return storage.get(path)

        def write(path: str, content: str, **kwargs: object) -> None:
            storage[path] = content

        user_count = User.objects.count()
        team_count = Team.objects.count()
        with (
            patch("posthog.storage.object_storage.read", side_effect=read),
            patch("posthog.storage.object_storage.write", side_effect=write) as writes,
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            seeded = self._seed(self.team.id, self.user.id)
            repeated = self._seed(self.team.id, self.user.id)

        assert repeated == seeded
        assert callbacks == []
        assert writes.call_count == 1
        assert User.objects.count() == user_count
        assert Team.objects.count() == team_count

        inbox = self.client.get(f"/api/projects/{self.team.id}/signals/reports/?view=for_you")
        assert inbox.status_code == 200, inbox.content
        reports = inbox.json()["results"]
        assert {row["id"] for row in reports} == set(seeded["report_ids"])
        assert {row["status"] for row in reports} == {"ready", "pending_input"}
        for report_id in seeded["report_ids"]:
            artefacts = self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report_id}/artefacts/")
            assert artefacts.status_code == 200, artefacts.content
            assert {row["type"] for row in artefacts.json()["results"]} >= {"note", "suggested_reviewers"}

        tasks_url = f"/api/projects/{self.team.id}/tasks/"
        chats = self.client.get(f"{tasks_url}?created_by={self.user.id}&exclude_origin_product=signals_scout")
        assert chats.status_code == 200, chats.content
        assert [row["id"] for row in chats.json()["results"]] == seeded["task_ids"]
        task_id = seeded["task_ids"][0]
        run_id = seeded["run_ids"][0]
        assert chats.json()["results"][0]["latest_run"]["status"] == "completed"
        with patch("posthog.storage.object_storage.read", side_effect=read):
            logs = self.client.get(f"{tasks_url}{task_id}/runs/{run_id}/logs/")
        assert logs.status_code == 200, logs.content
        entries = [json.loads(line) for line in logs.content.decode().splitlines()]
        assert entries[0]["notification"]["params"]["update"]["sessionUpdate"] == "user_message"
        assert "saved demo conversation" in entries[1]["notification"]["params"]["update"]["content"]["text"]

        edit = self.client.patch(f"{tasks_url}{task_id}/", {"title": "My demo title"}, format="json")
        assert edit.status_code == 200, edit.content
        with patch("posthog.storage.object_storage.read", side_effect=read):
            assert self._seed(self.team.id, self.user.id) == seeded
        assert self.client.get(f"{tasks_url}{task_id}/").json()["title"] == "My demo title"

        other_team = Team.objects.create(organization=self.organization, name="Other local project")
        assert self.client.get(f"/api/projects/{other_team.id}/signals/reports/?view=for_you").json()["results"] == []
        assert (
            self.client.get(f"/api/projects/{other_team.id}/tasks/?created_by={self.user.id}").json()["results"] == []
        )
        assert self.client.get(f"/api/projects/{other_team.id}/tasks/{task_id}/").status_code == 404

        other_user = User.objects.create_user(email="other-demo@example.com", first_name="Other", password="test")
        self.organization.members.add(other_user)
        self.client.force_login(other_user)
        assert self.client.get(f"/api/projects/{self.team.id}/signals/reports/?view=for_you").json()["results"] == []
        assert self.client.get(f"{tasks_url}?created_by={other_user.id}").json()["results"] == []

    def test_rejects_a_user_outside_the_project_organization(self) -> None:
        outsider = User.objects.create_user(email="outside-demo@example.com", first_name="Outside", password="test")
        with self.assertRaisesMessage(CommandError, "must belong to the project's organization"):
            self._seed(self.team.id, outsider.id)
