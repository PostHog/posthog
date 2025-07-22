from typing import Any
from unittest import mock

from rest_framework import status

from posthog.models.utils import uuid7
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
            "deleted": False,
            "version": 0,
            "created_at": mock.ANY,
            "item_id": None,
            "item_context": None,
            "scope": "Notebook",
            "tagged_users": [],
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
            "deleted": False,
            "version": 1,
            "created_at": mock.ANY,
            "item_id": None,
            "item_context": None,
            "scope": "Notebook",
            "tagged_users": [],
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

    def test_create_comment_with_tagged_users(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Original content with @a_user",
                "tagged_users": [str(self.user.uuid)],
                "scope": "Notebook",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["tagged_users"] == [str(self.user.uuid)]

    def test_create_comment_tagged_users_filters_invalid_uuids(self) -> None:
        unknown_user = str(uuid7())
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Original content with @a_user",
                "tagged_users": [str(self.user.uuid), unknown_user],
                "scope": "Notebook",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        # Should only include the valid user UUID
        assert response.json()["tagged_users"] == [str(self.user.uuid)]

    def test_update_comment_with_tagged_users(self) -> None:
        # Create comment initially without tagged users
        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Original content",
                "scope": "Notebook",
            },
        )

        # Update to add tagged users
        unknown_user = str(uuid7())
        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {
                "content": "Updated content with @user",
                "tagged_users": [str(self.user.uuid), unknown_user],
            },
        )

        assert response.status_code == status.HTTP_200_OK
        # Should only include the valid user UUID
        assert response.json()["tagged_users"] == [str(self.user.uuid)]

    def test_update_comment_tagged_users_change_detection(self) -> None:
        # Create comment with initial tagged users
        unknown_user_1 = str(uuid7())
        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Original content",
                "scope": "Notebook",
                "tagged_users": [unknown_user_1],
            },
        )

        # Update to add new tagged user (should log activity for new user only)
        unknown_user_2 = str(uuid7())
        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {
                "content": "Updated content with more users",
                "tagged_users": [unknown_user_1, str(self.user.uuid), unknown_user_2],
            },
        )

        assert response.status_code == status.HTTP_200_OK
        # Should only include the valid user UUID (unknown users filtered out)
        assert response.json()["tagged_users"] == [str(self.user.uuid)]

    def test_activity_logging_when_users_tagged_in_comment(self) -> None:
        content = "Important comment with @alice"
        tagged_users = [str(self.user.uuid)]

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": content,
                "tagged_users": tagged_users,
                "scope": "Notebook",
                "item_id": "test-item-id",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED

        self._assert_activity_log([])

    def test_activity_logging_when_updating_tagged_users(self) -> None:
        unknown_user = str(uuid7())
        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Original content with @old_user",
                "tagged_users": [unknown_user],
                "scope": "Dashboard",
                "item_id": "dashboard-123",
            },
        )

        # Update to add new tagged user
        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {
                "content": "Updated content with @old_user and @new_user",
                "tagged_users": [unknown_user, str(self.user.uuid)],
            },
        )

        assert response.status_code == status.HTTP_200_OK

        self._assert_activity_log(
            [
                {
                    "activity": "tagged_user",
                    "created_at": mock.ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "tagged_user",
                                "after": {
                                    "comment_content": "Updated content with @old_user and @new_user",
                                    "comment_item_id": "dashboard-123",
                                    "comment_scope": "Dashboard",
                                    "comment_source_comment_id": None,
                                    "tagged_user": str(self.user.uuid),
                                },
                                "before": None,
                                "field": None,
                                "type": "Comment",
                            },
                        ],
                        "name": str(self.user.uuid),
                        "short_id": None,
                        "trigger": None,
                        "type": None,
                    },
                    "id": "0198338d-2b8a-0000-dcdc-456a976fcbe3",
                    "is_system": False,
                    "item_id": "dashboard-123",
                    "organization_id": str(self.team.organization_id),
                    "scope": "Dashboard",
                    "unread": False,
                    "user": self._user_for_activity_log(),
                    "was_impersonated": False,
                },
                {
                    "activity": "commented",
                    "created_at": mock.ANY,
                    "detail": {
                        "changes": [
                            {
                                "action": "created",
                                "after": "Original content with @old_user",
                                "before": None,
                                "field": "content",
                                "type": "Comment",
                            },
                        ],
                        "name": None,
                        "short_id": None,
                        "trigger": None,
                        "type": None,
                    },
                    "id": "0198338d-2b74-0000-6722-e54e3e1622b6",
                    "is_system": False,
                    "item_id": "dashboard-123",
                    "organization_id": None,
                    "scope": "Dashboard",
                    "unread": False,
                    "user": self._user_for_activity_log(),
                    "was_impersonated": None,
                },
            ]
        )

    def test_activity_logging_for_comment_replies_with_tagged_users(self) -> None:
        parent_comment = self._create_comment(
            {
                "content": "Parent comment",
                "scope": "Notebook",
                "item_id": "notebook-123",
            }
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Reply with @user",
                "tagged_users": [str(self.user.uuid)],
                "source_comment": parent_comment["id"],
                "scope": "Notebook",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

        # For replies, the scope should be "Comment" and item_id should be the parent comment ID
        self._assert_activity_log([])

    def _assert_activity_log(self, expected: list[dict]) -> None:
        activity_response = self.client.get(f"/api/projects/{self.team.id}/activity_log/")
        assert activity_response.status_code == status.HTTP_200_OK
        assert activity_response.json()["results"] == expected

    def _user_for_activity_log(self):
        return {
            "distinct_id": self.user.distinct_id,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "hedgehog_config": None,
            "id": self.user.id,
            "is_email_verified": None,
            "last_name": "",
            "role_at_organization": None,
            "uuid": str(self.user.uuid),
        }
