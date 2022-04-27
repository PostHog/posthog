from uuid import uuid4

from dateutil.relativedelta import relativedelta
from freezegun.api import freeze_time

from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording_list import ClickhouseSessionRecordingList
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.models import Cohort, Person
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.session_recordings.test.test_session_recording_list import factory_session_recordings_list_test
from posthog.test.base import _create_event, test_with_materialized_columns


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestClickhouseSessionRecordingsList(ClickhouseTestMixin, factory_session_recordings_list_test(ClickhouseSessionRecordingList, _create_event, _create_session_recording_event, Action.objects.create, ActionStep.objects.create)):  # type: ignore
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    @test_with_materialized_columns(["$current_url"])
    def test_event_filter_with_person_properties(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(team=self.team, distinct_ids=["user2"], properties={"email": "bla2"})
        self.create_snapshot("user", "1", self.base_time)
        self.create_event("user", self.base_time)
        self.create_snapshot("user", "1", self.base_time + relativedelta(seconds=30))
        self.create_snapshot("user2", "2", self.base_time)
        self.create_event("user2", self.base_time)
        self.create_snapshot("user2", "2", self.base_time + relativedelta(seconds=30))
        filter = SessionRecordingsFilter(
            team=self.team,
            data={"properties": [{"key": "email", "value": ["bla"], "operator": "exact", "type": "person"}],},
        )
        session_recording_list_instance = ClickhouseSessionRecordingList(filter=filter, team=self.team)
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

                self.create_snapshot("user", "1", self.base_time)
                self.create_event("user", self.base_time, team=self.team)
                self.create_snapshot("user", "1", self.base_time + relativedelta(seconds=30))
                self.create_snapshot("user2", "2", self.base_time)
                self.create_event("user2", self.base_time, team=self.team)
                self.create_snapshot("user2", "2", self.base_time + relativedelta(seconds=30))
                filter = SessionRecordingsFilter(
                    team=self.team,
                    data={"properties": [{"key": "id", "value": cohort.pk, "operator": None, "type": "cohort"}],},
                )
                session_recording_list_instance = ClickhouseSessionRecordingList(filter=filter, team=self.team)
                (session_recordings, _) = session_recording_list_instance.run()
                self.assertEqual(len(session_recordings), 1)
                self.assertEqual(session_recordings[0]["session_id"], "2")

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    @test_with_materialized_columns(["$current_url"])
    def test_event_filter_with_matching_on_session_id(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        self.create_snapshot("user", "1", self.base_time, window_id="1")
        self.create_event("user", self.base_time, properties={"$session_id": "1"})
        self.create_event("user", self.base_time, event_name="$autocapture", properties={"$session_id": "2"})
        self.create_snapshot("user", "1", self.base_time + relativedelta(seconds=30), window_id="1")
        filter = SessionRecordingsFilter(
            team=self.team, data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )
        session_recording_list_instance = ClickhouseSessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$autocapture", "type": "events", "order": 0, "name": "$autocapture"}]},
        )
        session_recording_list_instance = ClickhouseSessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    @test_with_materialized_columns(["$current_url"])
    def test_event_filter_matching_with_no_session_id(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        self.create_snapshot("user", "1", self.base_time, window_id="1")
        self.create_event("user", self.base_time)
        self.create_snapshot("user", "1", self.base_time + relativedelta(seconds=30), window_id="1")
        self.create_event("user", self.base_time + relativedelta(seconds=31), event_name="$autocapture")

        # Pageview within timestamps matches recording
        filter = SessionRecordingsFilter(
            team=self.team, data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )
        session_recording_list_instance = ClickhouseSessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

        # Pageview outside timestamps does not match recording
        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$autocapture", "type": "events", "order": 0, "name": "$autocapture"}]},
        )
        session_recording_list_instance = ClickhouseSessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)
