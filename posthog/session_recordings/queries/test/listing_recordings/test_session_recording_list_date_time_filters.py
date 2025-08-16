from datetime import datetime
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Person
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.session_recordings.queries.test.listing_recordings.base_test_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import snapshot_clickhouse_queries


class TestSessionRecordingListDateTimeFilters(BaseTestSessionRecordingsList):
    def test_date_from_filter(self):
        user = "test_date_from_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        produce_replay_summary(
            distinct_id=user,
            session_id="three days before base time",
            first_timestamp=(self.an_hour_ago - relativedelta(days=3, seconds=100)),
            last_timestamp=(self.an_hour_ago - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id="two days before base time",
            first_timestamp=(self.an_hour_ago - relativedelta(days=2, seconds=100)),
            last_timestamp=(self.an_hour_ago - relativedelta(days=2)),
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids({"date_from": self.an_hour_ago.strftime("%Y-%m-%d")}, [])

        self.assert_query_matches_session_ids(
            {"date_from": (self.an_hour_ago - relativedelta(days=2)).strftime("%Y-%m-%d")},
            ["two days before base time"],
        )

    @parameterized.expand(
        [
            (
                "that searching from 20 days ago excludes sessions past TTL",
                20,
            ),
            (
                "that searching from 21 days ago still excludes sessions past TTL",
                21,
            ),
            (
                "that even searching from 22 days ago (exactly at TTL boundary) excludes sessions past TTL",
                22,
            ),
        ]
    )
    @snapshot_clickhouse_queries
    def test_date_from_filter_respects_ttl(self, _name: str, days_ago: int):
        with freeze_time(self.an_hour_ago):
            user = "test_date_from_filter_cannot_search_before_ttl-user"
            Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

            # Create a session past TTL (22 days old)
            produce_replay_summary(
                distinct_id=user,
                session_id="storage is past ttl",
                first_timestamp=(self.an_hour_ago - relativedelta(days=22)),
                # an illegally long session but it started 22 days ago
                last_timestamp=(self.an_hour_ago - relativedelta(days=3)),
                team_id=self.team.id,
            )

            # Create a session within TTL (19 days old)
            produce_replay_summary(
                distinct_id=user,
                session_id="storage is not past ttl",
                first_timestamp=(self.an_hour_ago - relativedelta(days=19)),
                last_timestamp=(self.an_hour_ago - relativedelta(days=2)),
                team_id=self.team.id,
            )

            self.assert_query_matches_session_ids(
                {"date_from": (self.an_hour_ago - relativedelta(days=days_ago)).strftime("%Y-%m-%d")},
                ["storage is not past ttl"],
            )

    @snapshot_clickhouse_queries
    def test_date_to_filter(self):
        user = "test_date_to_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        produce_replay_summary(
            distinct_id=user,
            session_id="three days before base time",
            first_timestamp=(self.an_hour_ago - relativedelta(days=3, seconds=100)),
            last_timestamp=(self.an_hour_ago - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=user,
            session_id="two days before base time",
            first_timestamp=(self.an_hour_ago - relativedelta(days=2, seconds=100)),
            last_timestamp=(self.an_hour_ago - relativedelta(days=2)),
            team_id=self.team.id,
        )

        self.assert_query_matches_session_ids(
            {"date_to": (self.an_hour_ago - relativedelta(days=4)).strftime("%Y-%m-%d")}, []
        )

        self.assert_query_matches_session_ids(
            {"date_to": (self.an_hour_ago - relativedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")},
            ["three days before base time"],
        )

    def test_recording_that_spans_time_bounds(self):
        user = "test_recording_that_spans_time_bounds-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        day_line = datetime(2021, 11, 5)
        session_id = f"session-one-{user}"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(day_line - relativedelta(hours=3)),
            last_timestamp=(day_line + relativedelta(hours=3)),
            team_id=self.team.id,
        )

        (session_recordings, _, _) = self.filter_recordings_by(
            {
                "date_to": day_line.strftime("%Y-%m-%d"),
                "date_from": (day_line - relativedelta(days=10)).strftime("%Y-%m-%d"),
            }
        )

        assert [{"session_id": session_id, "duration": 6 * 60 * 60}] == [
            {"session_id": sr["session_id"], "duration": sr["duration"]} for sr in session_recordings
        ]

    def test_ttl_days(self):
        # hobby is 21 days
        assert ttl_days(self.team) == 21

        with self.is_cloud(True):
            # free users are 30 days
            with freeze_time("2023-09-01T12:00:01Z"):
                assert ttl_days(self.team) == 30

            self.team.organization.available_product_features = [
                {"key": AvailableFeature.RECORDINGS_FILE_EXPORT, "name": AvailableFeature.RECORDINGS_FILE_EXPORT}
            ]

            # paid is 90 days
            with freeze_time("2023-12-01T12:00:01Z"):
                assert ttl_days(self.team) == 90

    @snapshot_clickhouse_queries
    def test_listing_ignores_future_replays(self):
        with freeze_time("2023-08-29T12:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="29th Aug")

        with freeze_time("2023-08-30T14:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="30th Aug 1400")

        with freeze_time("2023-09-01T12:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="1st-sep")

        with freeze_time("2023-09-02T12:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="2nd-sep")

        with freeze_time("2023-09-03T12:00:01Z"):
            produce_replay_summary(team_id=self.team.id, session_id="3rd-sep")

        # before the recording on the thirtieth so should exclude it
        with freeze_time("2023-08-30T12:00:01Z"):
            # recordings in the future don't show
            self.assert_query_matches_session_ids(None, ["29th Aug"])
