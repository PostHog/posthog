from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun.api import freeze_time

from posthog.models import Cohort, Person, Team
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList
from posthog.session_recordings.test.test_factory import create_chunked_snapshots, create_snapshot
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    snapshot_clickhouse_queries,
    with_materialized_columns,
)


class TestClickhouseSessionRecordingsList(ClickhouseTestMixin, APIBaseTest):
    def create_action(self, name, team_id=None, properties=[]):
        if team_id is None:
            team_id = self.team.pk
        action = Action.objects.create(team_id=team_id, name=name)
        ActionStep.objects.create(action=action, event=name, properties=properties)
        return action

    def create_event(
        self,
        distinct_id,
        timestamp,
        team=None,
        event_name="$pageview",
        properties={"$os": "Windows 95", "$current_url": "aloha.com/2"},
    ):
        if team is None:
            team = self.team
        return _create_event(
            team=team, event=event_name, timestamp=timestamp, distinct_id=distinct_id, properties=properties
        )

    @property
    def base_time(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0)

    @with_materialized_columns(["$current_url"])
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_basic_query(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=10),
            team_id=self.team.id,
        )
        create_snapshot(
            distinct_id="user",
            session_id="2",
            timestamp=self.base_time + relativedelta(seconds=20),
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, more_recordings_available) = session_recording_list_instance.run()

        self.assertEqual(len(session_recordings), 2)
        self.assertEqual(session_recordings[0]["start_time"], self.base_time + relativedelta(seconds=20))
        self.assertEqual(session_recordings[0]["session_id"], "2")
        self.assertEqual(session_recordings[0]["distinct_id"], "user")

        self.assertEqual(session_recordings[1]["start_time"], self.base_time)
        self.assertEqual(session_recordings[1]["session_id"], "1")
        self.assertEqual(session_recordings[1]["distinct_id"], "user")
        self.assertEqual(more_recordings_available, False)

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_recordings_dont_leak_data_between_teams(self):
        another_team = Team.objects.create(organization=self.organization)
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(team=another_team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=another_team.pk)
        create_snapshot(distinct_id="user", session_id="2", timestamp=self.base_time, team_id=self.team.id)

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "2")
        self.assertEqual(session_recordings[0]["distinct_id"], "user")

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_all_sessions_recording_object_keys(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["distinct_id"], "user")
        self.assertEqual(session_recordings[0]["start_time"], self.base_time)
        self.assertEqual(session_recordings[0]["end_time"], self.base_time + relativedelta(seconds=30))
        self.assertEqual(session_recordings[0]["duration"], 30)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_event_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        self.create_event("user", self.base_time, properties={"$session_id": "1", "$window_id": "1"})
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")
        self.assertEqual(len(session_recordings[0]["matching_events"][0]["events"]), 1)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["timestamp"], self.base_time)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["window_id"], "1")

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$autocapture", "type": "events", "order": 0, "name": "$autocapture"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @with_materialized_columns(["$current_url", "$browser"])
    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_event_filter_with_properties(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        self.create_event(
            "user", self.base_time, properties={"$browser": "Chrome", "$session_id": "1", "$window_id": "1"}
        )
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [{"key": "$browser", "value": ["Chrome"], "operator": "exact", "type": "event"}],
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")
        self.assertEqual(len(session_recordings[0]["matching_events"][0]["events"]), 1)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["timestamp"], self.base_time)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["window_id"], "1")

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [{"key": "$browser", "value": ["Firefox"], "operator": "exact", "type": "event"}],
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_multiple_event_filters(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        self.create_event("user", self.base_time, properties={"$session_id": "1", "$window_id": "1"})
        self.create_event(
            "user", self.base_time, properties={"$session_id": "1", "$window_id": "1"}, event_name="new-event"
        )
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"},
                    {"id": "new-event", "type": "events", "order": 0, "name": "new-event"},
                ]
            },
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")
        self.assertEqual(len(session_recordings[0]["matching_events"][0]["events"]), 1)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["timestamp"], self.base_time)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["window_id"], "1")
        self.assertEqual(len(session_recordings[0]["matching_events"][1]["events"]), 1)
        self.assertEqual(session_recordings[0]["matching_events"][1]["events"][0]["timestamp"], self.base_time)
        self.assertEqual(session_recordings[0]["matching_events"][1]["events"][0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["matching_events"][1]["events"][0]["window_id"], "1")

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"},
                    {"id": "new-event2", "type": "events", "order": 0, "name": "new-event2"},
                ]
            },
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @with_materialized_columns(["$current_url", "$browser"])
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_action_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        action1 = self.create_action(
            "custom-event",
            properties=[
                {"key": "$browser", "value": "Firefox"},
                {"key": "$session_id", "value": "1"},
                {"key": "$window_id", "value": "1"},
            ],
        )
        action2 = self.create_action(
            name="custom-event",
            properties=[{"key": "$session_id", "value": "1"}, {"key": "$window_id", "value": "1"}],
        )

        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        self.create_event(
            "user",
            self.base_time,
            event_name="custom-event",
            properties={"$browser": "Chrome", "$session_id": "1", "$window_id": "1"},
        )
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        # An action with properties
        filter = SessionRecordingsFilter(
            team=self.team,
            data={"actions": [{"id": action1.id, "type": "actions", "order": 1, "name": "custom-event"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

        # An action without properties
        filter = SessionRecordingsFilter(
            team=self.team,
            data={"actions": [{"id": action2.id, "type": "actions", "order": 1, "name": "custom-event"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")
        self.assertEqual(len(session_recordings[0]["matching_events"][0]["events"]), 1)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["timestamp"], self.base_time)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["window_id"], "1")

        # Adding properties to an action
        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "actions": [
                    {
                        "id": action2.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                        "properties": [{"key": "$browser", "value": ["Firefox"], "operator": "exact", "type": "event"}],
                    }
                ]
            },
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_all_sessions_recording_object_keys_with_entity_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        self.create_event("user", self.base_time, properties={"$session_id": "1", "$window_id": "1"})
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["distinct_id"], "user")
        self.assertEqual(session_recordings[0]["start_time"], self.base_time)
        self.assertEqual(session_recordings[0]["end_time"], self.base_time + relativedelta(seconds=30))
        self.assertEqual(session_recordings[0]["duration"], 30)
        self.assertEqual(len(session_recordings[0]["matching_events"][0]["events"]), 1)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["timestamp"], self.base_time)
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["window_id"], "1")

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_duration_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        create_snapshot(distinct_id="user", session_id="2", timestamp=self.base_time, team_id=self.team.id)
        create_snapshot(
            distinct_id="user",
            session_id="2",
            timestamp=self.base_time + relativedelta(minutes=4),
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(
            team=self.team,
            data={"session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}'},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "2")

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"lt"}'},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_date_from_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time - relativedelta(days=3),
            team_id=self.team.id,
        )
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time - relativedelta(days=3) + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(team=self.team, data={"date_from": self.base_time.strftime("%Y-%m-%d")})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

        filter = SessionRecordingsFilter(
            team=self.team, data={"date_from": (self.base_time - relativedelta(days=4)).strftime("%Y-%m-%d")}
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_date_to_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time - relativedelta(days=3),
            team_id=self.team.id,
        )
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time - relativedelta(days=3) + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team, data={"date_to": (self.base_time - relativedelta(days=4)).strftime("%Y-%m-%d")}
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

        filter = SessionRecordingsFilter(team=self.team, data={"date_to": (self.base_time).strftime("%Y-%m-%d")})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_recording_that_spans_time_bounds(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        day_line = datetime(2021, 11, 5)
        create_snapshot(
            distinct_id="user", session_id="1", timestamp=day_line - relativedelta(hours=3), team_id=self.team.id
        )
        create_snapshot(
            distinct_id="user", session_id="1", timestamp=day_line + relativedelta(hours=3), team_id=self.team.id
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "date_to": day_line.strftime("%Y-%m-%d"),
                "date_from": (day_line - relativedelta(days=10)).strftime("%Y-%m-%d"),
            },
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")
        self.assertEqual(session_recordings[0]["duration"], 6 * 60 * 60)

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_person_id_filter(self):
        p = Person.objects.create(team=self.team, distinct_ids=["user", "user2"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        create_snapshot(
            distinct_id="user2",
            session_id="2",
            timestamp=self.base_time + relativedelta(seconds=10),
            team_id=self.team.id,
        )
        create_snapshot(
            distinct_id="user3",
            session_id="3",
            timestamp=self.base_time + relativedelta(seconds=20),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(team=self.team, data={"person_uuid": str(p.uuid)})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)
        self.assertEqual(session_recordings[0]["session_id"], "2")
        self.assertEqual(session_recordings[1]["session_id"], "1")

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_all_filters_at_once(self):
        p = Person.objects.create(team=self.team, distinct_ids=["user", "user2"], properties={"email": "bla"})
        action2 = self.create_action(name="custom-event")

        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time - relativedelta(days=3),
            team_id=self.team.id,
        )
        self.create_event("user", self.base_time - relativedelta(days=3))
        self.create_event(
            "user",
            self.base_time - relativedelta(days=3),
            event_name="custom-event",
            properties={"$browser": "Chrome"},
        )
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time - relativedelta(days=3) + relativedelta(hours=6),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "person_uuid": str(p.uuid),
                "date_to": (self.base_time + relativedelta(days=3)).strftime("%Y-%m-%d"),
                "date_from": (self.base_time - relativedelta(days=10)).strftime("%Y-%m-%d"),
                "session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}',
                "events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}],
                "actions": [{"id": action2.id, "type": "actions", "order": 1, "name": "custom-event"}],
            },
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_pagination(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        create_snapshot(
            distinct_id="user",
            session_id="2",
            timestamp=self.base_time + relativedelta(seconds=10),
            team_id=self.team.id,
        )
        create_snapshot(
            distinct_id="user",
            session_id="3",
            timestamp=self.base_time + relativedelta(seconds=20),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(team=self.team, data={"limit": 2})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, more_recordings_available) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)
        self.assertEqual(session_recordings[0]["session_id"], "3")
        self.assertEqual(session_recordings[1]["session_id"], "2")
        self.assertEqual(more_recordings_available, True)

        filter = SessionRecordingsFilter(team=self.team, data={"limit": 2, "offset": 0})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, more_recordings_available) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)
        self.assertEqual(session_recordings[0]["session_id"], "3")
        self.assertEqual(session_recordings[1]["session_id"], "2")
        self.assertEqual(more_recordings_available, True)

        filter = SessionRecordingsFilter(team=self.team, data={"limit": 2, "offset": 1})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, more_recordings_available) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 2)
        self.assertEqual(session_recordings[0]["session_id"], "2")
        self.assertEqual(session_recordings[1]["session_id"], "1")
        self.assertEqual(more_recordings_available, False)

        filter = SessionRecordingsFilter(team=self.team, data={"limit": 2, "offset": 2})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, more_recordings_available) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")
        self.assertEqual(more_recordings_available, False)

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_recording_without_fullsnapshot_dont_appear(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time,
            has_full_snapshot=False,
            team_id=self.team.id,
        )
        filter = SessionRecordingsFilter(team=self.team, data={"no-filter": True})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_teams_dont_leak_event_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        another_team = Team.objects.create(organization=self.organization)

        create_snapshot(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
        self.create_event(1, self.base_time + relativedelta(seconds=15), team=another_team)
        create_snapshot(
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + relativedelta(seconds=30),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )

        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    @with_materialized_columns(person_properties=["email"])
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
            data={"properties": [{"key": "email", "value": ["bla"], "operator": "exact", "type": "person"}]},
        )
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], "1")

    @snapshot_clickhouse_queries
    @with_materialized_columns(["$current_url"])
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
                    data={"properties": [{"key": "id", "value": cohort.pk, "operator": None, "type": "cohort"}]},
                )
                session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
                (session_recordings, _) = session_recording_list_instance.run()
                self.assertEqual(len(session_recordings), 1)
                self.assertEqual(session_recordings[0]["session_id"], "2")

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    @with_materialized_columns(["$current_url"])
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
            team=self.team, data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]}
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
    @with_materialized_columns(["$current_url"])
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
            team=self.team, data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]}
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

    @freeze_time("2021-01-21T20:00:00.000Z")
    # @snapshot_clickhouse_queries
    def test_event_duration_is_calculated_from_summary(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        # Creates 1 full snapshot
        create_chunked_snapshots(
            team_id=self.team.id,
            snapshot_count=1,
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time,
            window_id="1",
            has_full_snapshot=True,
            source=3,
        )

        # Creates 10 click events at 1 second intervals
        create_chunked_snapshots(
            team_id=self.team.id,
            snapshot_count=10,
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + timedelta(minutes=1),
            window_id="1",
            has_full_snapshot=False,
            source=2,
        )

        # Creates 10 input events at 1 second intervals
        create_chunked_snapshots(
            team_id=self.team.id,
            snapshot_count=10,
            distinct_id="user",
            session_id="1",
            timestamp=self.base_time + timedelta(minutes=2),
            window_id="1",
            has_full_snapshot=False,
            source=5,
        )

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
        (session_recordings, more_recordings_available) = session_recording_list_instance.run()

        assert len(session_recordings) == 1

        assert session_recordings[0]["start_time"] == self.base_time + relativedelta(seconds=0)
        # Currently duration is loaded from the timestamp. This chunked snapshot will have a timestamp of the first event
        assert session_recordings[0]["end_time"] == self.base_time + relativedelta(minutes=2, seconds=9)
