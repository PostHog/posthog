from typing import Any
from unittest import mock

from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestComments(APIBaseTest, QueryMatchingTest):
    def _create_comment(self, data=None) -> Any:
        if data is None:
            data = {}
        payload = {
            "content": "my content",
            "scope": "Notebook",
        }

        payload.update(data)

        return self.client.post(
            f"/api/projects/{self.team.id}/comments",
            payload,
        ).json()

    def test_creates_comment_with_validation_errors(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "This is a comment",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "required",
            "detail": "This field is required.",
            "attr": "scope",
        }

    def test_creates_comment_successfully(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "This is a comment",
                "scope": "Notebook",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["created_by"]["id"] == self.user.id
        assert response.json() == {
            "id": mock.ANY,
            "created_by": response.json()["created_by"],
            "content": "This is a comment",
            "rich_content": None,
            "deleted": False,
            "version": 0,
            "created_at": mock.ANY,
            "item_id": None,
            "item_context": None,
            "scope": "Notebook",
            "source_comment": None,
        }

    def test_updates_content_and_increments_version(self) -> None:
        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "This is a comment",
                "scope": "Notebook",
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {
                "content": "This is an edited comment",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "id": mock.ANY,
            "created_by": response.json()["created_by"],
            "content": "This is an edited comment",
            "rich_content": None,
            "deleted": False,
            "version": 1,
            "created_at": mock.ANY,
            "item_id": None,
            "item_context": None,
            "scope": "Notebook",
            "source_comment": None,
        }

    def test_empty_comments_list(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "next": None,
            "previous": None,
            "results": [],
        }

    def test_lists_comments(self) -> None:
        self._create_comment({"content": "comment 1"})
        self._create_comment({"content": "comment 2"})
        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert len(response.json()["results"]) == 2

        assert response.json()["results"][0]["content"] == "comment 2"
        assert response.json()["results"][1]["content"] == "comment 1"

    def test_lists_comments_filtering(self) -> None:
        self._create_comment({"content": "comment notebook-1", "scope": "Notebook", "item_id": "1"})
        self._create_comment({"content": "comment notebook-2", "scope": "Notebook", "item_id": "2"})
        self._create_comment({"content": "comment dashboard-1", "scope": "Dashboard", "item_id": "1"})

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=Notebook")
        assert len(response.json()["results"]) == 2
        assert response.json()["results"][0]["content"] == "comment notebook-2"
        assert response.json()["results"][1]["content"] == "comment notebook-1"

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=Notebook&item_id=2")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["content"] == "comment notebook-2"

    def test_lists_comments_thread(self) -> None:
        initial_comment = self._create_comment({"content": "comment notebook-1", "scope": "Notebook", "item_id": "1"})
        self._create_comment({"content": "comment reply", "source_comment": initial_comment["id"]})
        self._create_comment({"content": "comment other reply", "source_comment": initial_comment["id"]})
        self._create_comment({"content": "comment elsewhere"})

        for url in [
            f"/api/projects/{self.team.id}/comments/{initial_comment['id']}/thread",
            f"/api/projects/{self.team.id}/comments/?source_comment={initial_comment['id']}",
        ]:
            response = self.client.get(url)
            assert len(response.json()["results"]) == 2
            assert response.json()["results"][0]["content"] == "comment other reply"
            assert response.json()["results"][1]["content"] == "comment reply"
