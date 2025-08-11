import json
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models import Person, SessionRecording, Comment
from posthog.models.utils import uuid7
from posthog.session_recordings.models.session_recording_event import (
    SessionRecordingViewed,
)
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
)


class TestSessionRecordingsCommentFiltering(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        sync_execute("TRUNCATE TABLE sharded_events")
        sync_execute("TRUNCATE TABLE person")
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")
        SessionRecordingViewed.objects.all().delete()
        SessionRecording.objects.all().delete()
        Person.objects.all().delete()

        with freeze_time("2023-01-01T12:00:00Z"):
            self.session_id = str(uuid7())
            self.produce_replay_summary(
                "user",
                self.session_id,
                now() - relativedelta(days=1),
                team_id=self.team.pk,
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
            ("no_match", "xyz123", []),
            ("exact_match", "needle", ["session_with_needle"]),
            ("partial_match", "need", ["session_with_needle", "session_with_need"]),
            ("case_insensitive", "NEEDLE", ["session_with_needle"]),
            ("phrase_match", "bug fix", ["session_with_bug"]),
            ("emoji_match", "💖", ["session_with_emoji"]),
            ("emoji_not_match", "😱", []),
        ]
    )
    def test_comment_text_search(self, _name: str, search_text: str, expected_session_ids: list[str]) -> None:
        session_no_comment = str(uuid7())
        session_with_needle = "session_with_needle"
        session_with_bug = "session_with_bug"
        session_with_emoji = "session_with_emoji"
        session_with_need = "session_with_need"

        base_time = now() - timedelta(hours=1)

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

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings",
            {
                "kind": "RecordingsQuery",
                "order": "start_time",
                "order_direction": "DESC",
                "date_from": "-3d",
                "comment_text": json.dumps(
                    {"key": "comment_text", "value": search_text, "operator": "icontains", "type": "recording"}
                ),
                "limit": "20",
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()
        actual_session_ids = [recording["id"] for recording in response_data["results"]]

        assert set(actual_session_ids) == set(
            expected_session_ids
        ), f"Search '{search_text}': Expected {expected_session_ids}, got {actual_session_ids}"
