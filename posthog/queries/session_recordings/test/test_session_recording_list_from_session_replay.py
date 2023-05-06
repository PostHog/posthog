from uuid import uuid4

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun.api import freeze_time

from posthog.models import Person
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.team import Team
from posthog.queries.session_recordings.SessionRecordingListFromReplaySummary import (
    SessionRecordingListFromReplaySummary,
)
from posthog.queries.session_recordings.test.session_replay_sql import produce_replay_summary
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    also_test_with_materialized_columns,
    snapshot_clickhouse_queries,
)


class TestClickhouseSessionRecordingsListFromSessionReplay(ClickhouseTestMixin, APIBaseTest):
    # this test does not create any session_recording_events, only writes to the session_replay summary table
    # it is a pair with test_session_recording_list
    # it should pass all the same tests but without needing the session_recording_events table at all

    def create_action(self, name, team_id=None, properties=None):
        if team_id is None:
            team_id = self.team.pk
        if properties is None:
            properties = []
        action = Action.objects.create(team_id=team_id, name=name)
        ActionStep.objects.create(action=action, event=name, properties=properties)
        return action

    def create_event(
        self,
        distinct_id,
        timestamp,
        team=None,
        event_name="$pageview",
        properties=None,
    ):
        if team is None:
            team = self.team
        if properties is None:
            properties = {"$os": "Windows 95", "$current_url": "aloha.com/2"}
        return _create_event(
            team=team, event=event_name, timestamp=timestamp, distinct_id=distinct_id, properties=properties
        )

    @property
    def base_time(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0)

    @also_test_with_materialized_columns(["$current_url"])
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_basic_query(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        session_id_one = str(uuid4())
        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=self.base_time.isoformat().replace("T", " "),
            last_timestamp=(self.base_time + relativedelta(seconds=20)).isoformat().replace("T", " "),
            distinct_id="user",
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=50 * 1000 * 0.5,  # 50% of the total expected duration
        )
        produce_replay_summary(
            session_id=session_id_one,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=(self.base_time + relativedelta(seconds=10)).isoformat(),
            last_timestamp=(self.base_time + relativedelta(seconds=50)).isoformat(),
            distinct_id="user",
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=0,  # 30% of the total expected duration
        )

        session_id_two = str(uuid4())
        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp=(self.base_time + relativedelta(seconds=20)).isoformat(),
            last_timestamp=(self.base_time + relativedelta(seconds=2000)).isoformat(),
            distinct_id="user",
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=1980 * 1000 * 0.4,  # 40% of the total expected duration
        )

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, more_recordings_available) = session_recording_list_instance.run()

        self.assertEqual(len(session_recordings), 2)

        assert session_recordings == [
            {
                "session_id": session_id_two,
                "team_id": self.team.pk,
                "distinct_id": "user",
                "click_count": 2,
                "keypress_count": 2,
                "mouse_activity_count": 2,
                "duration": 1980,
                "active_time": 0.4,
                "start_time": self.base_time + relativedelta(seconds=20),
                "end_time": self.base_time + relativedelta(seconds=2000),
            },
            {
                "session_id": session_id_one,
                "team_id": self.team.pk,
                "distinct_id": "user",
                "click_count": 4,
                "keypress_count": 4,
                "mouse_activity_count": 4,
                "duration": 50,
                "active_time": 0.5,
                "start_time": self.base_time,
                "end_time": self.base_time + relativedelta(seconds=50),
            },
        ]

        self.assertEqual(more_recordings_available, False)

    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_recordings_dont_leak_data_between_teams(self):
        another_team = Team.objects.create(organization=self.organization)
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(team=another_team, distinct_ids=["user"], properties={"email": "bla"})

        session_id_one = str(uuid4())
        produce_replay_summary(
            session_id=session_id_one,
            team_id=another_team.pk,
            distinct_id="user",
            first_timestamp=self.base_time.isoformat().replace("T", " "),
            last_timestamp=(self.base_time + relativedelta(seconds=20)).isoformat().replace("T", " "),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=20 * 1000 * 0.5,  # 50% of the total expected duration
        )
        session_id_two = str(uuid4())
        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            distinct_id="user",
            first_timestamp=self.base_time.isoformat().replace("T", " "),
            last_timestamp=(self.base_time + relativedelta(seconds=20)).isoformat().replace("T", " "),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=20 * 1000 * 0.5,  # 50% of the total expected duration
        )

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], session_id_two)
        self.assertEqual(session_recordings[0]["distinct_id"], "user")

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_event_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        session_id_one = str(uuid4())
        produce_replay_summary(
            distinct_id="user",
            session_id=session_id_one,
            first_timestamp=self.base_time.isoformat(),
            team_id=self.team.id,
        )
        self.create_event(
            "user", self.base_time, properties={"$session_id": session_id_one, "$window_id": str(uuid4())}
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=session_id_one,
            first_timestamp=self.base_time.isoformat(),
            team_id=self.team.id,
        )

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], session_id_one)

        filter = SessionRecordingsFilter(
            team=self.team,
            data={"events": [{"id": "$autocapture", "type": "events", "order": 0, "name": "$autocapture"}]},
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @also_test_with_materialized_columns(["$current_url", "$browser"])
    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21T20:00:00.000Z")
    def test_event_filter_with_properties(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        session_id_one = str(uuid4())
        produce_replay_summary(
            distinct_id="user",
            session_id=session_id_one,
            first_timestamp=self.base_time.isoformat(),
            team_id=self.team.id,
        )
        self.create_event(
            "user",
            self.base_time,
            properties={"$browser": "Chrome", "$session_id": session_id_one, "$window_id": str(uuid4())},
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=session_id_one,
            first_timestamp=(self.base_time + relativedelta(seconds=30)).isoformat(),
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
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], session_id_one)

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
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_multiple_event_filters(self):
        session_id = str(uuid4())
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        produce_replay_summary(
            distinct_id="user", session_id=session_id, first_timestamp=self.base_time.isoformat(), team_id=self.team.id
        )
        self.create_event("user", self.base_time, properties={"$session_id": session_id, "$window_id": "1"})
        self.create_event(
            "user", self.base_time, properties={"$session_id": session_id, "$window_id": "1"}, event_name="new-event"
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=session_id,
            first_timestamp=(self.base_time + relativedelta(seconds=30)).isoformat(),
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
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()

        self.assertEqual(len(session_recordings), 1)
        self.assertEqual(session_recordings[0]["session_id"], session_id)

        filter = SessionRecordingsFilter(
            team=self.team,
            data={
                "events": [
                    {"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"},
                    {"id": "new-event2", "type": "events", "order": 0, "name": "new-event2"},
                ]
            },
        )
        session_recording_list_instance = SessionRecordingListFromReplaySummary(filter=filter, team=self.team)
        (session_recordings, _) = session_recording_list_instance.run()
        self.assertEqual(len(session_recordings), 0)


#     @also_test_with_materialized_columns(["$current_url", "$browser"])
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_action_filter(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         action1 = self.create_action(
#             "custom-event",
#             properties=[
#                 {"key": "$browser", "value": "Firefox"},
#                 {"key": "$session_id", "value": "1"},
#                 {"key": "$window_id", "value": "1"},
#             ],
#         )
#         action2 = self.create_action(
#             name="custom-event",
#             properties=[{"key": "$session_id", "value": "1"}, {"key": "$window_id", "value": "1"}],
#         )
#
#         produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#         self.create_event(
#             "user",
#             self.base_time,
#             event_name="custom-event",
#             properties={"$browser": "Chrome", "$session_id": "1", "$window_id": "1"},
#         )
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time + relativedelta(seconds=30),
#             team_id=self.team.id,
#         )
#
#         # An action with properties
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"actions": [{"id": action1.id, "type": "actions", "order": 1, "name": "custom-event"}]},
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 0)
#
#         # An action without properties
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"actions": [{"id": action2.id, "type": "actions", "order": 1, "name": "custom-event"}]},
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#         self.assertEqual(len(session_recordings[0]["matching_events"][0]["events"]), 1)
#         self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["timestamp"], self.base_time)
#         self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["session_id"], "1")
#         self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["window_id"], "1")
#
#         # Adding properties to an action
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={
#                 "actions": [
#                     {
#                         "id": action2.id,
#                         "type": "actions",
#                         "order": 1,
#                         "name": "custom-event",
#                         "properties": [
#                             {"key": "$browser", "value": ["Firefox"], "operator": "exact", "type": "event"}
#                         ],
#                     }
#                 ]
#             },
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 0)
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_all_sessions_recording_object_keys_with_entity_filter(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#         self.create_event("user", self.base_time, properties={"$session_id": "1", "$window_id": "1"})
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time + relativedelta(seconds=30),
#             team_id=self.team.id,
#         )
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#         self.assertEqual(session_recordings[0]["distinct_id"], "user")
#         self.assertEqual(session_recordings[0]["start_time"], self.base_time)
#         self.assertEqual(session_recordings[0]["end_time"], self.base_time + relativedelta(seconds=30))
#         self.assertEqual(session_recordings[0]["duration"], 30)
#         self.assertEqual(len(session_recordings[0]["matching_events"][0]["events"]), 1)
#         self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["timestamp"], self.base_time)
#         self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["session_id"], "1")
#         self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["window_id"], "1")
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_duration_filter(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time + relativedelta(seconds=30),
#             team_id=self.team.id,
#         )
#
#         produce_replay_summary(distinct_id="user", session_id="2", timestamp=self.base_time, team_id=self.team.id)
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="2",
#             timestamp=self.base_time + relativedelta(minutes=4),
#             team_id=self.team.id,
#         )
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}'},
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "2")
#
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"lt"}'},
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_date_from_filter(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time - relativedelta(days=3),
#             team_id=self.team.id,
#         )
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time - relativedelta(days=3) + relativedelta(seconds=30),
#             team_id=self.team.id,
#         )
#
#         filter = SessionRecordingsFilter(team=self.team, data={"date_from": self.base_time.strftime("%Y-%m-%d")})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 0)
#
#         filter = SessionRecordingsFilter(
#             team=self.team, data={"date_from": (self.base_time - relativedelta(days=4)).strftime("%Y-%m-%d")}
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_date_to_filter(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time - relativedelta(days=3),
#             team_id=self.team.id,
#         )
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time - relativedelta(days=3) + relativedelta(seconds=30),
#             team_id=self.team.id,
#         )
#
#         filter = SessionRecordingsFilter(
#             team=self.team, data={"date_to": (self.base_time - relativedelta(days=4)).strftime("%Y-%m-%d")}
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 0)
#
#         filter = SessionRecordingsFilter(team=self.team, data={"date_to": (self.base_time).strftime("%Y-%m-%d")})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_recording_that_spans_time_bounds(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         day_line = datetime(2021, 11, 5)
#         produce_replay_summary(
#             distinct_id="user", session_id="1", timestamp=day_line - relativedelta(hours=3), team_id=self.team.id
#         )
#         produce_replay_summary(
#             distinct_id="user", session_id="1", timestamp=day_line + relativedelta(hours=3), team_id=self.team.id
#         )
#
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={
#                 "date_to": day_line.strftime("%Y-%m-%d"),
#                 "date_from": (day_line - relativedelta(days=10)).strftime("%Y-%m-%d"),
#             },
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#         self.assertEqual(session_recordings[0]["duration"], 6 * 60 * 60)
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_person_id_filter(self):
#         p = Person.objects.create(team=self.team, distinct_ids=["user", "user2"], properties={"email": "bla"})
#         produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#         produce_replay_summary(
#             distinct_id="user2",
#             session_id="2",
#             timestamp=self.base_time + relativedelta(seconds=10),
#             team_id=self.team.id,
#         )
#         produce_replay_summary(
#             distinct_id="user3",
#             session_id="3",
#             timestamp=self.base_time + relativedelta(seconds=20),
#             team_id=self.team.id,
#         )
#
#         filter = SessionRecordingsFilter(team=self.team, data={"person_uuid": str(p.uuid)})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 2)
#         self.assertEqual(session_recordings[0]["session_id"], "2")
#         self.assertEqual(session_recordings[1]["session_id"], "1")
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_all_filters_at_once(self):
#         p = Person.objects.create(team=self.team, distinct_ids=["user", "user2"], properties={"email": "bla"})
#         action2 = self.create_action(name="custom-event")
#
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time - relativedelta(days=3),
#             team_id=self.team.id,
#         )
#         self.create_event("user", self.base_time - relativedelta(days=3), properties={"$session_id": "1"})
#         self.create_event(
#             "user",
#             self.base_time - relativedelta(days=3),
#             event_name="custom-event",
#             properties={"$browser": "Chrome", "$session_id": "1"},
#         )
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time - relativedelta(days=3) + relativedelta(hours=6),
#             team_id=self.team.id,
#         )
#
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={
#                 "person_uuid": str(p.uuid),
#                 "date_to": (self.base_time + relativedelta(days=3)).strftime("%Y-%m-%d"),
#                 "date_from": (self.base_time - relativedelta(days=10)).strftime("%Y-%m-%d"),
#                 "session_recording_duration": '{"type":"recording","key":"duration","value":60,"operator":"gt"}',
#                 "events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}],
#                 "actions": [{"id": action2.id, "type": "actions", "order": 1, "name": "custom-event"}],
#             },
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_pagination(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="2",
#             timestamp=self.base_time + relativedelta(seconds=10),
#             team_id=self.team.id,
#         )
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="3",
#             timestamp=self.base_time + relativedelta(seconds=20),
#             team_id=self.team.id,
#         )
#
#         filter = SessionRecordingsFilter(team=self.team, data={"limit": 2})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, more_recordings_available) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 2)
#         self.assertEqual(session_recordings[0]["session_id"], "3")
#         self.assertEqual(session_recordings[1]["session_id"], "2")
#         self.assertEqual(more_recordings_available, True)
#
#         filter = SessionRecordingsFilter(team=self.team, data={"limit": 2, "offset": 0})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, more_recordings_available) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 2)
#         self.assertEqual(session_recordings[0]["session_id"], "3")
#         self.assertEqual(session_recordings[1]["session_id"], "2")
#         self.assertEqual(more_recordings_available, True)
#
#         filter = SessionRecordingsFilter(team=self.team, data={"limit": 2, "offset": 1})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, more_recordings_available) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 2)
#         self.assertEqual(session_recordings[0]["session_id"], "2")
#         self.assertEqual(session_recordings[1]["session_id"], "1")
#         self.assertEqual(more_recordings_available, False)
#
#         filter = SessionRecordingsFilter(team=self.team, data={"limit": 2, "offset": 2})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, more_recordings_available) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#         self.assertEqual(more_recordings_available, False)
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_recording_without_fullsnapshot_dont_appear(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time,
#             has_full_snapshot=False,
#             team_id=self.team.id,
#         )
#         filter = SessionRecordingsFilter(team=self.team, data={"no-filter": True})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 0)
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     def test_teams_dont_leak_event_filter(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         another_team = Team.objects.create(organization=self.organization)
#
#         produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#         self.create_event(1, self.base_time + relativedelta(seconds=15), team=another_team)
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time + relativedelta(seconds=30),
#             team_id=self.team.id,
#         )
#
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
#         )
#
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 0)
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     @snapshot_clickhouse_queries
#     @also_test_with_materialized_columns(person_properties=["email"])
#     def test_event_filter_with_person_properties(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         Person.objects.create(team=self.team, distinct_ids=["user2"], properties={"email": "bla2"})
#         produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#         self.create_event("user", self.base_time)
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time + relativedelta(seconds=30),
#             team_id=self.team.id,
#         )
#         produce_replay_summary(distinct_id="user2", session_id="2", timestamp=self.base_time, team_id=self.team.id)
#         self.create_event("user2", self.base_time)
#         produce_replay_summary(
#             distinct_id="user2",
#             session_id="2",
#             timestamp=self.base_time + relativedelta(seconds=30),
#             team_id=self.team.id,
#         )
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"properties": [{"key": "email", "value": ["bla"], "operator": "exact", "type": "person"}]},
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#
#     @snapshot_clickhouse_queries
#     @also_test_with_materialized_columns(["$current_url"])
#     def test_event_filter_with_cohort_properties(self):
#         with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
#             with freeze_time("2021-08-21T20:00:00.000Z"):
#                 Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#                 Person.objects.create(
#                     team=self.team, distinct_ids=["user2"], properties={"email": "bla2", "$some_prop": "some_val"}
#                 )
#                 cohort = Cohort.objects.create(
#                     team=self.team,
#                     name="cohort1",
#                     groups=[{"properties": [{"key": "$some_prop", "value": "some_val", "type": "person"}]}],
#                 )
#                 cohort.calculate_people_ch(pending_version=0)
#
#                 produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#                 self.create_event("user", self.base_time, team=self.team)
#                 produce_replay_summary(
#                     distinct_id="user",
#                     session_id="1",
#                     timestamp=self.base_time + relativedelta(seconds=30),
#                     team_id=self.team.id,
#                 )
#                 produce_replay_summary(distinct_id="user2", session_id="2", timestamp=self.base_time, team_id=self.team.id)
#                 self.create_event("user2", self.base_time, team=self.team)
#                 produce_replay_summary(
#                     distinct_id="user2",
#                     session_id="2",
#                     timestamp=self.base_time + relativedelta(seconds=30),
#                     team_id=self.team.id,
#                 )
#                 filter = SessionRecordingsFilter(
#                     team=self.team,
#                     data={"properties": [{"key": "id", "value": cohort.pk, "operator": None, "type": "cohort"}]},
#                 )
#                 session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#                 (session_recordings, _) = session_recording_list_instance.run()
#                 self.assertEqual(len(session_recordings), 1)
#                 self.assertEqual(session_recordings[0]["session_id"], "2")
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     @snapshot_clickhouse_queries
#     @also_test_with_materialized_columns(["$current_url"])
#     def test_event_filter_with_matching_on_session_id(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#         produce_replay_summary(
#             distinct_id="user", session_id="1", timestamp=self.base_time, window_id="1", team_id=self.team.id
#         )
#         self.create_event("user", self.base_time, properties={"$session_id": "1"})
#         self.create_event("user", self.base_time, event_name="$autocapture", properties={"$session_id": "2"})
#         produce_replay_summary(
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time + relativedelta(seconds=30),
#             window_id="1",
#             team_id=self.team.id,
#         )
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"events": [{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]},
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 1)
#         self.assertEqual(session_recordings[0]["session_id"], "1")
#
#         filter = SessionRecordingsFilter(
#             team=self.team,
#             data={"events": [{"id": "$autocapture", "type": "events", "order": 0, "name": "$autocapture"}]},
#         )
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, _) = session_recording_list_instance.run()
#         self.assertEqual(len(session_recordings), 0)
#
#     @freeze_time("2021-01-21T20:00:00.000Z")
#     # @snapshot_clickhouse_queries
#     def test_event_duration_is_calculated_from_summary(self):
#         Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#
#         # Creates 1 full snapshot
#         create_chunked_snapshots(
#             team_id=self.team.id,
#             snapshot_count=1,
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time,
#             window_id="1",
#             has_full_snapshot=True,
#             source=3,
#         )
#
#         # Creates 10 click events at 1 second intervals
#         create_chunked_snapshots(
#             team_id=self.team.id,
#             snapshot_count=10,
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time + timedelta(minutes=1),
#             window_id="1",
#             has_full_snapshot=False,
#             source=2,
#         )
#
#         # Creates 10 input events at 1 second intervals
#         create_chunked_snapshots(
#             team_id=self.team.id,
#             snapshot_count=10,
#             distinct_id="user",
#             session_id="1",
#             timestamp=self.base_time + timedelta(minutes=2),
#             window_id="1",
#             has_full_snapshot=False,
#             source=5,
#         )
#
#         filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
#         session_recording_list_instance = session_recording_list(filter=filter, team=self.team)
#         (session_recordings, more_recordings_available) = session_recording_list_instance.run()
#
#         assert len(session_recordings) == 1
#
#         assert session_recordings[0]["start_time"] == self.base_time + relativedelta(seconds=0)
#         # Currently duration is loaded from the timestamp. This chunked snapshot will have a timestamp of the first event
#         assert session_recordings[0]["end_time"] == self.base_time + relativedelta(minutes=2, seconds=9)
#
# return TestClickhouseSessionRecordingsList
#
#
# class TestClickhouseSessionRecordingsList(session_recording_list_test_factory(SessionRecordingList)):  # type: ignore
# @also_test_with_materialized_columns(event_properties=["$current_url", "$browser"], person_properties=["email"])
# @snapshot_clickhouse_queries
# @freeze_time("2021-01-21T20:00:00.000Z")
# def test_event_filter_with_hogql_properties(self):
#     Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
#     produce_replay_summary(distinct_id="user", session_id="1", timestamp=self.base_time, team_id=self.team.id)
#     self.create_event(
#         "user", self.base_time, properties={"$browser": "Chrome", "$session_id": "1", "$window_id": "1"}
#     )
#     produce_replay_summary(
#         distinct_id="user",
#         session_id="1",
#         timestamp=self.base_time + relativedelta(seconds=30),
#         team_id=self.team.id,
#     )
#     filter = SessionRecordingsFilter(
#         team=self.team,
#         data={
#             "events": [
#                 {
#                     "id": "$pageview",
#                     "type": "events",
#                     "order": 0,
#                     "name": "$pageview",
#                     "properties": [
#                         {"key": "properties.$browser == 'Chrome'", "type": "hogql"},
#                         {"key": "person.properties.email == 'bla'", "type": "hogql"},
#                     ],
#                 }
#             ]
#         },
#     )
#     session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
#     (session_recordings, _) = session_recording_list_instance.run()
#     self.assertEqual(len(session_recordings), 1)
#     self.assertEqual(session_recordings[0]["session_id"], "1")
#     self.assertEqual(len(session_recordings[0]["matching_events"][0]["events"]), 1)
#     self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["timestamp"], self.base_time)
#     self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["session_id"], "1")
#     self.assertEqual(session_recordings[0]["matching_events"][0]["events"][0]["window_id"], "1")
#
#     filter = SessionRecordingsFilter(
#         team=self.team,
#         data={
#             "events": [
#                 {
#                     "id": "$pageview",
#                     "type": "events",
#                     "order": 0,
#                     "name": "$pageview",
#                     "properties": [{"key": "properties.$browser == 'Firefox'", "type": "hogql"}],
#                 }
#             ]
#         },
#     )
#     session_recording_list_instance = SessionRecordingList(filter=filter, team=self.team)
#     (session_recordings, _) = session_recording_list_instance.run()
#     self.assertEqual(len(session_recordings), 0)
