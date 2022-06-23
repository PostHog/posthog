from dateutil.relativedelta import relativedelta
from freezegun.api import freeze_time

from posthog.models import Cohort, Person
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList
from posthog.queries.session_recordings.test.test_session_recording_list import factory_session_recordings_list_test
from posthog.session_recordings.test.test_factory import create_snapshot
from posthog.test.base import (
    ClickhouseTestMixin,
    _create_event,
    snapshot_clickhouse_queries,
    test_with_materialized_columns,
)


class TestClickhouseSessionRecordingsList(ClickhouseTestMixin, factory_session_recordings_list_test(SessionRecordingList, _create_event, Action.objects.create, ActionStep.objects.create)):  # type: ignore
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    @test_with_materialized_columns(["$current_url"])
    def test_event_filter_with_person_properties(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(team=self.team, distinct_ids=["user2"], properties={"email": "bla2"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        self.create_event("user", self.base_time)
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        create_snapshot(distinct_id="user2", session_id="2", timestamp=self.base_time, team_id=self.team.id)
        self.create_event("user2", self.base_time)
        create_snapshot(
            distinct_id="user2",
            session_id="2",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(
            team=self.team,
            data={"properties": [{"key": "email", "value": ["bla"], "operator": "exact", "type": "person"}],},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

    @snapshot_clickhouse_queries
    @test_with_materialized_columns(["$current_url"])
    def test_event_filter_with_cohort_properties(self):
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2021-08-21T20:00:00.000Z"):
                Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
                Person.objects.create(
                    team=self.team, distinct_ids=["user2"], properties={"email": "bla2", "$some_prop": "some_val"}
                )
                cohort = Cohort.objects.create(
                    team=self.team,
                    name="cohort1",
                    groups=[{"properties": [{"key": "$some_prop", "value": "some_val", "type": "person"}]}],
                )
                cohort.calculate_people_ch(pending_version=0)

                create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
                self.create_event("user", self.base_time, team=self.team)
                create_snapshot(
                    distinct_id="user",
                    session_id="1",
                    timestamp=self.base_time + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                create_snapshot(distinct_id="user2", session_id="2", timestamp=self.base_time, team_id=self.team.id)
                self.create_event("user2", self.base_time, team=self.team)
                create_snapshot(
                    distinct_id="user2",
                    session_id="2",
                    timestamp=self.base_time + relativedelta(seconds=30),
                    team_id=self.team.id,
                )
                filter = SessionRecordingsFilter(
                    team=self.team,
                    data={"properties": [{"key": "id", "value": cohort.pk, "operator": None, "type": "cohort"}],},
                )
                session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
                (session_recordings, _) = session_recording_list_instance.run()
                self.assertEqual(len(session_recordings), 1)
                self.assertEqual(session_recordings[0]["session_id"], "2")

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    @test_with_materialized_columns(["$current_url"])
    def test_event_filter_with_matching_on_session_id(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(
            distinct_id="user", session_id="1", timestamp=self.base_time, window_id="1", team_id=self.team.id
        )
        self.create_event("user", self.base_time, properties={"$session_id": "1"})
        self.create_event("user", self.base_time, event_name="$autocapture", properties={"$session_id": "2"})
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            window_id="1",
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(
            team=self.team, data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$autocapture", "type": "events", "order": 0, "name": "$autocapture"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    @test_with_materialized_columns(["$current_url"])
    def test_event_filter_matching_with_no_session_id(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(
            distinct_id="user", session_id="1", timestamp=self.base_time, window_id="1", team_id=self.team.id
        )
        self.create_event("user", self.base_time)
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            window_id="1",
            team_id=self.team.id,
        )
        self.create_event("user", self.base_time + relativedelta(seconds=31), event_name="$autocapture")

        # Pageview within timestamps matches recording
        filter = SessionRecordingsFilter(
            team=self.team, data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

        # Pageview outside timestamps does not match recording
        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$autocapture", "type": "events", "order": 0, "name": "$autocapture"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)
