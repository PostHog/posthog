from typing import List, Dict, Optional
from unittest import mock
from unittest.mock import patch, MagicMock

from freezegun import freeze_time
from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_team import create_team
from posthog.models import Team, Organization
from posthog.models.user import User
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries


class TestNotebooks(APIBaseTest, QueryMatchingTest):
    def created_activity(self, item_id: str, short_id: str) -> Dict:
        return {
            "activity": "created",
            "created_at": mock.ANY,
            "detail": {
                "changes": None,
                "name": None,
                "short_id": short_id,
                "trigger": None,
                "type": None,
            },
            "item_id": item_id,
            "scope": "Notebook",
            "user": {
                "email": self.user.email,
                "first_name": self.user.first_name,
            },
        }

    def assert_notebook_activity(self, expected: List[Dict]) -> None:
        activity_response = self.client.get(f"/api/projects/{self.team.id}/notebooks/activity")
        assert activity_response.status_code == status.HTTP_200_OK

        activity: List[Dict] = activity_response.json()["results"]

        self.maxDiff = None
        assert activity == expected

    def test_empty_notebook_list(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }

    def test_basic_notebook_list(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/notebooks",
            data={"title": "Notebook One", "content": {"some": "kind", "of": "tip", "tap": "content"}},
        ).json()
        self.client.post(
            f"/api/projects/{self.team.id}/notebooks",
            data={"title": "Notebook Two", "content": {"some": "kind", "of": "tip", "tap": "content"}},
        ).json()

        response = self.client.get(f"/api/projects/{self.team.id}/notebooks?basic=true")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2
        assert set(response.json()["results"][0].keys()) == {
            "id",
            "short_id",
            "title",
            "version",
            "deleted",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
        }

    def test_cannot_list_deleted_notebook(self) -> None:
        notebook_one = self.client.post(f"/api/projects/{self.team.id}/notebooks", data={}).json()
        notebook_two = self.client.post(f"/api/projects/{self.team.id}/notebooks", data={}).json()
        notebook_three = self.client.post(f"/api/projects/{self.team.id}/notebooks", data={}).json()

        self.client.patch(f"/api/projects/{self.team.id}/notebooks/{notebook_two['short_id']}", data={"deleted": True})

        response = self.client.get(f"/api/projects/{self.team.id}/notebooks")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2
        assert [n["short_id"] for n in response.json()["results"]] == [
            notebook_three["short_id"],
            notebook_one["short_id"],
        ]

    @parameterized.expand(
        [
            ("without_content", None),
            ("with_content", {"some": "kind", "of": "tip", "tap": "content"}),
        ]
    )
    def test_create_a_notebook(self, _, content: Optional[Dict]) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/notebooks", data={"content": content})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {
            "id": response.json()["id"],
            "short_id": response.json()["short_id"],
            "content": content,
            "title": None,
            "version": 0,
            "created_at": mock.ANY,
            "created_by": response.json()["created_by"],
            "deleted": False,
            "last_modified_at": mock.ANY,
            "last_modified_by": response.json()["last_modified_by"],
        }

        self.assert_notebook_activity(
            [
                self.created_activity(item_id=response.json()["id"], short_id=response.json()["short_id"]),
            ],
        )

    def test_gets_individual_notebook_by_shortid(self) -> None:
        create_response = self.client.post(f"/api/projects/{self.team.id}/notebooks", data={})
        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/{create_response.json()['short_id']}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["short_id"] == create_response.json()["short_id"]

    @snapshot_postgres_queries
    def test_updates_notebook(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/notebooks/", data={})
        assert response.status_code == status.HTTP_201_CREATED
        response_json = response.json()
        assert "short_id" in response_json
        short_id = response_json["short_id"]

        with freeze_time("2022-01-02"):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/notebooks/{short_id}",
                {"content": {"some": "updated content"}, "version": response_json["version"], "title": "New title"},
            )

        assert response.json()["short_id"] == short_id
        assert response.json()["content"] == {"some": "updated content"}
        assert response.json()["last_modified_at"] == "2022-01-02T00:00:00Z"

        self.assert_notebook_activity(
            [
                self.created_activity(item_id=response.json()["id"], short_id=response.json()["short_id"]),
                {
                    "activity": "updated",
                    "created_at": mock.ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "created",
                                "after": "New title",
                                "before": None,
                                "field": "title",
                                "type": "Notebook",
                            },
                            {
                                "action": "created",
                                "after": {"some": "updated content"},
                                "before": None,
                                "field": "content",
                                "type": "Notebook",
                            },
                            {
                                "action": "changed",
                                "after": 1,
                                "before": 0,
                                "field": "version",
                                "type": "Notebook",
                            },
                        ],
                        "name": "New title",
                        "short_id": response.json()["short_id"],
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": response.json()["id"],
                    "scope": "Notebook",
                    "user": {"email": self.user.email, "first_name": self.user.first_name},
                },
            ],
        )

    def test_cannot_change_short_id(self) -> None:
        notebook = self.client.post(f"/api/projects/{self.team.id}/notebooks/", data={}).json()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook['short_id']}",
            {"short_id": "something else", "version": notebook["version"]},
        )
        # out of the box this is accepted _and_ ignored 🤷‍♀️
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["short_id"] == notebook["short_id"]

    def test_listing_does_not_leak_between_teams(self) -> None:
        another_team = Team.objects.create(organization=self.organization)
        another_user = User.objects.create_and_join(self.organization, "other@example.com", password="")

        self.client.force_login(another_user)
        response = self.client.post(f"/api/projects/{another_team.id}/notebooks", data={})
        assert response.status_code == status.HTTP_201_CREATED

        self.client.force_login(self.user)
        response = self.client.post(f"/api/projects/{self.team.id}/notebooks", data={})
        assert response.status_code == status.HTTP_201_CREATED
        this_team_notebook_short_id = response.json()["short_id"]

        response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["short_id"] == this_team_notebook_short_id

    def test_creating_does_not_leak_between_teams(self) -> None:
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)

        self.client.force_login(self.user)
        response = self.client.post(f"/api/projects/{another_team.id}/notebooks", data={})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_patching_does_not_leak_between_teams(self) -> None:
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other@example.com", password="")

        self.client.force_login(another_user)
        response = self.client.post(f"/api/projects/{another_team.id}/notebooks", data={})
        assert response.status_code == status.HTTP_201_CREATED

        self.client.force_login(self.user)
        response = self.client.patch(
            f"/api/projects/{another_team.id}/notebooks/{response.json()['short_id']}",
            data={"content": {"something": "here"}},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_get_via_valid_sharing_token(self, _patched_exporter_task: MagicMock) -> None:
        notebook_one = Notebook.objects.create(team=self.team, created_by=self.user, title="notebook one")

        enable_sharing_response = self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook_one.short_id}/sharing", {"enabled": True}
        )
        assert enable_sharing_response.status_code == status.HTTP_200_OK, enable_sharing_response.json()
        token = enable_sharing_response.json()["access_token"]

        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{notebook_one.short_id}?sharing_access_token={token}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        assert response.json()["short_id"] == notebook_one.short_id
        assert response.json()["title"] == notebook_one.title

    @patch("posthog.api.exports.exporter.export_asset.delay")
    def test_get_via_sharing_token(self, _patched_exporter_task: MagicMock) -> None:
        other_team = create_team(organization=self.organization)

        notebook_one = Notebook.objects.create(team=self.team, created_by=self.user, title="notebook one")
        notebook_two = Notebook.objects.create(team=self.team, created_by=self.user, title="notebook two")

        enable_sharing_response = self.client.patch(
            f"/api/projects/{self.team.id}/notebooks/{notebook_one.short_id}/sharing", {"enabled": True}
        )
        assert enable_sharing_response.status_code == status.HTTP_200_OK, enable_sharing_response.json()
        token = enable_sharing_response.json()["access_token"]

        self.client.logout()

        # Unallowed routes
        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{notebook_two.short_id}?sharing_access_token={token}"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(f"/api/projects/{self.team.id}/notebooks?sharing_access_token={token}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(f"/api/projects/12345/notebooks?sharing_access_token={token}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(
            f"/api/projects/{other_team.id}/notebooks/{notebook_one.short_id}?sharing_access_token={token}"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
