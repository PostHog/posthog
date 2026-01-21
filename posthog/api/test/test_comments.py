from typing import Any

from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status


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
            {"content": "This is a comment", "scope": "Notebook"},
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

    @parameterized.expand(
        [
            ("no_comments", [], "", 0),
            (
                "two_comments_different_scopes",
                [
                    {"content": "comment 1", "scope": "Notebook", "item_id": "1"},
                    {"content": "comment 2", "scope": "Dashboard", "item_id": "2"},
                ],
                "",
                2,
            ),
            (
                "filter_by_scope",
                [
                    {"content": "comment 1", "scope": "Notebook", "item_id": "1"},
                    {"content": "comment 2", "scope": "Dashboard", "item_id": "2"},
                ],
                "?scope=Notebook",
                1,
            ),
        ]
    )
    def test_count_comments(self, name: str, comments_to_create: list, query_params: str, expected_count: int) -> None:
        for comment_data in comments_to_create:
            self._create_comment(comment_data)

        response = self.client.get(f"/api/projects/{self.team.id}/comments/count{query_params}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"count": expected_count}

    @parameterized.expand(
        [
            (
                "excludes_only_the_2_emoji_reactions",
                [
                    {"content": "regular comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "another comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "👍", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {"content": "❤️", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {
                        "content": "comment with context",
                        "scope": "Notebook",
                        "item_id": "1",
                        "item_context": {"other_field": "value"},
                    },
                ],
                "?exclude_emoji_reactions=true",
                3,
            ),
            (
                "counts_all_comments_including_emojis",
                [
                    {"content": "regular comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "another comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "👍", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {"content": "❤️", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {
                        "content": "comment with context",
                        "scope": "Notebook",
                        "item_id": "1",
                        "item_context": {"other_field": "value"},
                    },
                ],
                "",
                5,
            ),
            (
                "only_notebook_comments_excluding_emoji_reactions",
                [
                    {"content": "regular comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "another comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "dashboard comment", "scope": "Dashboard", "item_id": "2"},
                    {"content": "👍", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {"content": "❤️", "scope": "Dashboard", "item_id": "2", "item_context": {"is_emoji": True}},
                ],
                "?scope=Notebook&exclude_emoji_reactions=true",
                2,
            ),
            (
                "includes_comments_with_is_emoji_false",
                [
                    {"content": "regular comment", "scope": "Notebook", "item_id": "1"},
                    {
                        "content": "explicitly not emoji",
                        "scope": "Notebook",
                        "item_id": "1",
                        "item_context": {"is_emoji": False},
                    },
                    {"content": "👍", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                ],
                "?exclude_emoji_reactions=true",
                2,
            ),
        ]
    )
    def test_count_comments_with_emoji_filtering(
        self, name: str, comments_to_create: list, query_params: str, expected_count: int
    ) -> None:
        for comment_data in comments_to_create:
            self._create_comment(comment_data)

        response = self.client.get(f"/api/projects/{self.team.id}/comments/count{query_params}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"count": expected_count}

    def test_creates_llm_trace_comment_successfully(self) -> None:
        trace_id = "test-trace-123"
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "This trace has high latency",
                "scope": "LLMTrace",
                "item_id": trace_id,
                "item_context": {"trace_id": trace_id},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["created_by"]["id"] == self.user.id
        assert response.json()["scope"] == "LLMTrace"
        assert response.json()["item_id"] == trace_id
        assert response.json()["content"] == "This trace has high latency"

    def test_filters_llm_trace_comments(self) -> None:
        trace_id_1 = "trace-1"
        trace_id_2 = "trace-2"

        # Create comments on different traces
        self._create_comment({"content": "Trace 1 comment", "scope": "LLMTrace", "item_id": trace_id_1})
        self._create_comment({"content": "Trace 2 comment", "scope": "LLMTrace", "item_id": trace_id_2})

        # Filter by LLMTrace scope
        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=LLMTrace")
        assert len(response.json()["results"]) == 2

        # Filter by specific trace
        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=LLMTrace&item_id={trace_id_1}")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["content"] == "Trace 1 comment"

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_extracts_mentions_from_rich_content_on_create(self, mock_send_email) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "mentioned@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Notebook",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Hey "},
                                {"type": "ph-mention", "attrs": {"id": mentioned_user.id}},
                                {"type": "text", "text": " check this out"},
                            ],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        assert call_args[0][1] == [mentioned_user.id]

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_extracts_mentions_from_rich_content_on_update(self, mock_send_email) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "mentioned_update@posthog.com", None)

        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "Original comment", "scope": "Notebook"},
        )

        mock_send_email.reset_mock()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {
                "content": "",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Edited to mention "},
                                {"type": "ph-mention", "attrs": {"id": mentioned_user.id}},
                            ],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        assert call_args[0][1] == [mentioned_user.id]

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_uses_explicit_mentions_field_when_provided(self, mock_send_email) -> None:
        from posthog.models import User

        mentioned_user_1 = User.objects.create_and_join(self.organization, "explicit_user1@posthog.com", None)
        mentioned_user_2 = User.objects.create_and_join(self.organization, "explicit_user2@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Notebook",
                "mentions": [mentioned_user_1.id, mentioned_user_2.id],
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Test"}],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        assert set(call_args[0][1]) == {mentioned_user_1.id, mentioned_user_2.id}

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_deduplicates_mentions_from_rich_content(self, mock_send_email) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "duplicate@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Notebook",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Hey "},
                                {"type": "ph-mention", "attrs": {"id": mentioned_user.id}},
                                {"type": "text", "text": " and "},
                                {"type": "ph-mention", "attrs": {"id": mentioned_user.id}},
                                {"type": "text", "text": " again"},
                            ],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        # Should only contain the user ID once, even though they were mentioned twice
        assert call_args[0][1] == [mentioned_user.id]
        assert len(call_args[0][1]) == 1

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_ignores_non_integer_ids_in_rich_content(self, mock_send_email) -> None:
        from posthog.models import User

        valid_user = User.objects.create_and_join(self.organization, "valid@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Notebook",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "ph-mention", "attrs": {"id": "invalid_string"}},
                                {"type": "ph-mention", "attrs": {"id": valid_user.id}},
                                {"type": "ph-mention", "attrs": {"id": None}},
                                {"type": "ph-mention", "attrs": {"id": 999.5}},
                            ],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        # Should only extract the valid integer ID, ignoring string, None, and float
        assert call_args[0][1] == [valid_user.id]
