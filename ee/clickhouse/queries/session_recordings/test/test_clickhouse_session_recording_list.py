from uuid import uuid4

from dateutil.relativedelta import relativedelta

from ee.clickhouse.models.action import Action, ActionStep
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording_list import ClickhouseSessionRecordingList
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models import Cohort, Person
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.session_recordings.test.test_session_recording_list import factory_session_recordings_list_test


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestClickhouseSessionRecordingsList(ClickhouseTestMixin, factory_session_recordings_list_test(ClickhouseSessionRecordingList, _create_event, _create_session_recording_event, Action.objects.create, ActionStep.objects.create)):  # type: ignore
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
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [{"key": "email", "value": ["bla"], "operator": "exact", "type": "person"}],
                    },
                ]
            }
        )
        session_recording_list_instance = ClickhouseSessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

    def test_event_filter_with_cohort_properties(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(
            team=self.team, distinct_ids=["user2"], properties={"email": "bla2", "$some_prop": "some_val"}
        )
        cohort = Cohort.objects.create(
            team=self.team, name="cohort1", groups=[{"properties": {"$some_prop": "some_val"}}]
        )
        self.create_snapshot("user", "1", self.base_time)
        self.create_event("user", self.base_time)
        self.create_snapshot("user", "1", self.base_time + relativedelta(seconds=30))
        self.create_snapshot("user2", "2", self.base_time)
        self.create_event("user2", self.base_time)
        self.create_snapshot("user2", "2", self.base_time + relativedelta(seconds=30))
        filter = SessionRecordingsFilter(
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [{"key": "id", "value": cohort.pk, "operator": None, "type": "cohort"}],
                    },
                ]
            }
        )
        session_recording_list_instance = ClickhouseSessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "2")
