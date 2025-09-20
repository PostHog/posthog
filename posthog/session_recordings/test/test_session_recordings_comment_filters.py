import json
from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status

from posthog.schema import PropertyOperator

from posthog.clickhouse.client import sync_execute
from posthog.models import Comment
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class TestSessionRecordingsCommentFiltering(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        sync_execute("TRUNCATE TABLE sharded_session_replay_events")

        session_no_comment = str(uuid7())
        session_with_needle = "session_with_needle"
        session_with_bug = "session_with_bug"
        session_with_emoji = "session_with_emoji"
        session_with_need = "session_with_need"

        base_time = now() - timedelta(hours=2)

        [
            self.produce_replay_summary(
                distinct_id=f"user{i}",
                session_id=x,
                timestamp=base_time + timedelta(minutes=i * 10),
            )
            for i, x in enumerate(
                [session_no_comment, session_with_needle, session_with_bug, session_with_emoji, session_with_need]
            )
        ]

        Comment.objects.create(
            team=self.team,
            content="This comment contains the word needle for searching",
            scope="recording",
            item_id=session_with_needle,
            created_by=self.user,
        )
        Comment.objects.create(
            team=self.team,
            content="This recording has two comments",
            scope="recording",
            item_id=session_with_needle,
            created_by=self.user,
        )
        Comment.objects.create(
            team=self.team,
            content="This comment contains the word need for searching",
            scope="recording",
            item_id=session_with_need,
            created_by=self.user,
        )
        Comment.objects.create(
            team=self.team,
            content="Fixed the bug fix issue in the login form",
            scope="recording",
            item_id=session_with_bug,
            created_by=self.user,
        )
        Comment.objects.create(
            team=self.team,
            content="Some unrelated content here",
            scope="recording",
            item_id=str(uuid7()),
            created_by=self.user,
        )
        Comment.objects.create(
            team=self.team,
            content="heart eyes 💖",
            scope="recording",
            item_id=session_with_emoji,
            created_by=self.user,
        )

    def produce_replay_summary(
        self,
        distinct_id,
        session_id,
        timestamp,
        team_id=None,
    ):
        if team_id is None:
            team_id = self.team.pk

        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            ensure_analytics_event_in_session=False,
        )

    @parameterized.expand(
        [
            ("no_match", "xyz123", PropertyOperator.ICONTAINS, []),
            ("contains whole word matching", "needle", PropertyOperator.ICONTAINS, ["session_with_needle"]),
            (
                "equals - exact match",
                ["Fixed the bug fix issue in the login form"],
                PropertyOperator.EXACT,
                ["session_with_bug"],
            ),
            (
                "contains partial word matching",
                "need",
                PropertyOperator.ICONTAINS,
                ["session_with_needle", "session_with_need"],
            ),
            ("case_insensitive", "NEEDLE", PropertyOperator.ICONTAINS, ["session_with_needle"]),
            ("phrase_match", "bug fix", PropertyOperator.ICONTAINS, ["session_with_bug"]),
            ("emoji_match", "💖", PropertyOperator.ICONTAINS, ["session_with_emoji"]),
            ("emoji_not_match", "😱", PropertyOperator.ICONTAINS, []),
            (
                "comments is set",
                "",
                PropertyOperator.IS_SET,
                ["session_with_needle", "session_with_bug", "session_with_emoji", "session_with_need"],
            ),
        ]
    )
    def test_comment_text_filtering(
        self, _name: str, search_text: str | list[str], operator: str, expected_session_ids: list[str]
    ) -> None:
        response_data = self._list_recordings_by_comment(search_text, operator)

        actual_session_ids = [recording["id"] for recording in response_data["results"]]
        assert set(actual_session_ids) == set(expected_session_ids)

    def test_empty_comment_text_does_no_filtering(self) -> None:
        """
        When comment text is empty, it should not filter out any recordings.
        It's considered an incomplete filter and ignored
        """
        response_data = self._list_recordings_by_comment("", PropertyOperator.ICONTAINS)

        actual_session_ids = [recording["id"] for recording in response_data["results"]]
        assert len(actual_session_ids) > 0, "Expected some recordings to be returned when comment text is empty"

    def _list_recordings_by_comment(self, search_text: str | list[str], operator: str) -> dict:
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings",
            {
                "kind": "RecordingsQuery",
                "order": "start_time",
                "order_direction": "DESC",
                "date_from": "-3d",
                "comment_text": json.dumps(
                    {"key": "comment_text", "value": search_text, "operator": operator, "type": "recording"}
                ),
                "limit": "20",
            },
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()
        return response_data
