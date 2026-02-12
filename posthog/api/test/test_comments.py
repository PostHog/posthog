from typing import Any

from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest import mock

from django.conf import settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.comment.utils import build_comment_item_url, extract_plain_text_from_rich_content


class TestComments(APIBaseTest, QueryMatchingTest):
    def _create_comment(self, data: dict | None = None) -> Any:
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

        self._create_comment({"content": "Trace 1 comment", "scope": "LLMTrace", "item_id": trace_id_1})
        self._create_comment({"content": "Trace 2 comment", "scope": "LLMTrace", "item_id": trace_id_2})

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=LLMTrace")
        assert len(response.json()["results"]) == 2

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=LLMTrace&item_id={trace_id_1}")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["content"] == "Trace 1 comment"

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_extracts_mentions_from_rich_content_on_create(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
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

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_extracts_mentions_from_rich_content_on_update(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
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

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_uses_explicit_mentions_field_when_provided(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
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

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_deduplicates_mentions_from_rich_content(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
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
        assert call_args[0][1] == [mentioned_user.id]
        assert len(call_args[0][1]) == 1

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_ignores_non_integer_ids_in_rich_content(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
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
        assert call_args[0][1] == [valid_user.id]

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_passes_slug_parameter_when_provided(self, mock_send_email) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "slug_test@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Replay",
                "item_id": "test-replay-id",
                "slug": "/replay/test-replay-id",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "ph-mention", "attrs": {"id": mentioned_user.id}}],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        # Verify slug is passed as 3rd argument
        assert call_args[0][2] == "/replay/test-replay-id"

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_slug_defaults_to_empty_string_when_not_provided(self, mock_send_email) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "no_slug@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Replay",
                "item_id": "test-replay-id",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "ph-mention", "attrs": {"id": mentioned_user.id}}],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        # Verify slug defaults to empty string
        assert call_args[0][2] == ""

    def test_soft_delete_comment_without_providing_content(self) -> None:
        # Create a comment
        existing = self._create_comment({"content": "This is a comment"})

        # Soft delete by setting deleted=True without providing content
        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing['id']}",
            {"deleted": True},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["deleted"] is True
        assert response.json()["content"] == "This is a comment"

    def test_soft_deleted_comments_excluded_from_list_by_default(self) -> None:
        # Create comments
        self._create_comment({"content": "comment 1"})
        comment_to_delete = self._create_comment({"content": "comment 2"})

        # Verify both exist
        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert len(response.json()["results"]) == 2

        # Soft delete
        self.client.patch(
            f"/api/projects/{self.team.id}/comments/{comment_to_delete['id']}",
            {"deleted": True},
        )

        # Verify deleted comment is excluded from list
        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["content"] == "comment 1"

    def test_hard_delete_returns_method_not_allowed(self) -> None:
        existing = self._create_comment({"content": "This is a comment"})

        response = self.client.delete(f"/api/projects/{self.team.id}/comments/{existing['id']}")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


class TestDiscussionMentionInternalEvents(APIBaseTest, QueryMatchingTest):
    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_produces_internal_event_on_comment_create(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(
            self.organization, "event_mention@posthog.com", None, first_name="MentionedUser"
        )

        self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Check this out",
                "scope": "Notebook",
                "item_id": "123",
                "mentions": [mentioned_user.id],
            },
        )

        assert mock_produce_event.called
        call_args = mock_produce_event.call_args
        assert call_args.kwargs["team_id"] == self.team.id
        event = call_args.kwargs["event"]
        assert event.event == "$discussion_mention_created"
        assert event.properties["mentioned_user_id"] == mentioned_user.id
        assert event.properties["mentioned_user_email"] == mentioned_user.email
        assert event.properties["scope"] == "Notebook"
        assert event.properties["item_id"] == "123"

    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_produces_internal_event_on_comment_update(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(
            self.organization, "update_mention@posthog.com", None, first_name="MentionedUser"
        )

        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "Original", "scope": "Notebook"},
        )

        mock_produce_event.reset_mock()

        self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {"content": "Updated", "mentions": [mentioned_user.id]},
        )

        assert mock_produce_event.called
        event = mock_produce_event.call_args.kwargs["event"]
        assert event.event == "$discussion_mention_created"

    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_self_mentions_do_not_produce_events(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "I mention myself",
                "scope": "Notebook",
                "mentions": [self.user.id],
            },
        )

        mock_produce_event.assert_not_called()

    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_event_properties_include_correct_user_data(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(
            self.organization, "data_test@posthog.com", None, first_name="TestUser"
        )

        self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Test content",
                "scope": "Insight",
                "item_id": "456",
                "mentions": [mentioned_user.id],
                "slug": "/insights/456",
            },
        )

        call_args = mock_produce_event.call_args
        event = call_args.kwargs["event"]
        person = call_args.kwargs["person"]

        assert event.properties["mentioned_user_id"] == mentioned_user.id
        assert event.properties["mentioned_user_email"] == "data_test@posthog.com"
        assert event.properties["mentioned_user_name"] == "TestUser"
        assert event.properties["commenter_user_id"] == self.user.id
        assert event.properties["commenter_user_email"] == self.user.email
        assert event.properties["scope"] == "Insight"
        assert event.properties["item_id"] == "456"
        assert event.properties["slug"] == "/insights/456"
        assert event.properties["team_name"] == self.team.name

        assert person.id == str(self.user.id)


class TestCommentHelperFunctions(APIBaseTest):
    @parameterized.expand(
        [
            ("with_slug", "Notebook", "123", "/notebook/abc", "/notebook/abc#panel=discussion"),
            (
                "with_slug_already_has_panel",
                "Notebook",
                "123",
                "/notebook/abc#panel=discussion",
                "/notebook/abc#panel=discussion",
            ),
            ("without_slug_notebook", "Notebook", "123", "", "/notebooks/123#panel=discussion"),
            ("without_slug_insight", "Insight", "456", "", "/insights/456#panel=discussion"),
            ("without_slug_dashboard", "Dashboard", "789", "", "/dashboard/789#panel=discussion"),
            ("without_slug_replay", "Replay", "rec_123", "", "/replay/rec_123#panel=discussion"),
            ("without_slug_feature_flag", "FeatureFlag", "10", "", "/feature_flags/10#panel=discussion"),
            ("unknown_scope_fallback", "UnknownScope", "123", "", "#panel=discussion"),
        ]
    )
    def test_build_comment_item_url(self, name: str, scope: str, item_id: str, slug: str, expected_suffix: str) -> None:
        result = build_comment_item_url(scope, item_id, slug if slug else None)
        assert result == f"{settings.SITE_URL}{expected_suffix}"

    @parameterized.expand(
        [
            ("simple_text", {"type": "doc", "content": [{"type": "text", "text": "Hello"}]}, "Hello"),
            (
                "with_mention",
                {
                    "type": "doc",
                    "content": [{"type": "ph-mention", "attrs": {"id": 1, "label": "John"}}],
                },
                "@John",
            ),
            (
                "mixed_content",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Hey "},
                                {"type": "ph-mention", "attrs": {"id": 1, "label": "Jane"}},
                                {"type": "text", "text": " check this"},
                            ],
                        }
                    ],
                },
                "Hey @Jane check this",
            ),
            ("empty_content", None, ""),
            ("empty_dict", {}, ""),
        ]
    )
    def test_extract_plain_text_from_rich_content(self, name: str, rich_content: dict | None, expected: str) -> None:
        result = extract_plain_text_from_rich_content(rich_content)
        assert result == expected
