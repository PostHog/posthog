from typing import Literal
from uuid import uuid4

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from parameterized import parameterized

from posthog.models import Person, GroupTypeMapping
from posthog.models.group.util import create_group
from posthog.models.team import Team
from posthog.session_recordings.queries.test.listing_recordings.base_test_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.session_recordings.queries.test.listing_recordings.test_utils import create_event
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import flush_persons_and_events, snapshot_clickhouse_queries


@freeze_time("2021-01-01T13:46:23")
class TestSessionRecordingsListMiscFilters(BaseTestSessionRecordingsList):
    @snapshot_clickhouse_queries
    def test_duration_filter(self):
        user = "test_duration_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = "session one is 29 seconds long"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=29)),
            team_id=self.team.id,
        )

        session_id_two = "session two is 61 seconds long"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_two,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=61)),
            team_id=self.team.id,
        )

        self._assert_query_matches_session_ids(
            {"having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"gt"}]'},
            [session_id_two],
        )

        self._assert_query_matches_session_ids(
            {"having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"lt"}]'},
            [session_id_one],
        )

    @parameterized.expand(
        [
            (
                "session 1 matches target flag is True",
                [{"type": "event", "key": "$feature/target-flag", "operator": "exact", "value": ["true"]}],
                ["1"],
            ),
            (
                "session 2 matches target flag is False",
                [{"type": "event", "key": "$feature/target-flag", "operator": "exact", "value": ["false"]}],
                ["2"],
            ),
            (
                "sessions 1 and 2 match target flag is set",
                [{"type": "event", "key": "$feature/target-flag", "operator": "is_set", "value": "is_set"}],
                ["1", "2"],
            ),
            (
                "sessions 3 and 4 match target flag is not set",
                [{"type": "event", "key": "$feature/target-flag", "operator": "is_not_set", "value": "is_not_set"}],
                ["3", "4"],
            ),
        ]
    )
    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_can_filter_for_flags(self, _name: str, properties: dict, expected: list[str]) -> None:
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})

        produce_replay_summary(
            distinct_id="user",
            session_id="1",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "1",
                "$window_id": "1",
                "$feature/target-flag": True,
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="2",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "2",
                "$window_id": "1",
                "$feature/target-flag": False,
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="3",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "3",
                "$window_id": "1",
                "$feature/flag-that-is-different": False,
            },
        )

        produce_replay_summary(
            distinct_id="user",
            session_id="4",
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        create_event(
            team=self.team,
            distinct_id="user",
            timestamp=self.an_hour_ago,
            properties={
                "$session_id": "4",
                "$window_id": "1",
            },
        )

        self._assert_query_matches_session_ids({"properties": properties}, expected)

    def test_recordings_dont_leak_data_between_teams(self):
        another_team = Team.objects.create(organization=self.organization)
        user = "test_recordings_dont_leak_data_between_teams-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        Person.objects.create(team=another_team, distinct_ids=[user], properties={"email": "bla"})

        session_id_one = f"test_recordings_dont_leak_data_between_teams-1-{str(uuid4())}"
        session_id_two = f"test_recordings_dont_leak_data_between_teams-2-{str(uuid4())}"

        produce_replay_summary(
            session_id=session_id_one,
            team_id=another_team.pk,
            distinct_id=user,
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=20),
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=20 * 1000 * 0.5,  # 50% of the total expected duration
        )

        produce_replay_summary(
            session_id=session_id_two,
            team_id=self.team.pk,
            distinct_id=user,
            first_timestamp=self.an_hour_ago,
            last_timestamp=self.an_hour_ago + relativedelta(seconds=20),
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=20 * 1000 * 0.5,  # 50% of the total expected duration
        )

        (session_recordings, _, _) = self._filter_recordings_by()

        assert [{"session": r["session_id"], "user": r["distinct_id"]} for r in session_recordings] == [
            {"session": session_id_two, "user": user}
        ]

    def test_teams_dont_leak_event_filter(self):
        user = "test_teams_dont_leak_event_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})
        another_team = Team.objects.create(organization=self.organization)

        session_id = f"test_teams_dont_leak_event_filter-{str(uuid4())}"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
        )
        create_event(distinct_id=user, timestamp=self.an_hour_ago + relativedelta(seconds=15), team=another_team)
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id,
            first_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ]
            },
            [],
        )

    def test_event_filter_with_two_events_and_multiple_teams(self):
        another_team = Team.objects.create(organization=self.organization)

        # two teams, user with the same properties
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        Person.objects.create(team=another_team, distinct_ids=["user"], properties={"email": "bla"})

        # a recording session with a pageview and a pageleave
        self._a_session_with_two_events(self.team, "1")
        self._a_session_with_two_events(another_team, "2")

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "$pageleave",
                        "type": "events",
                        "order": 0,
                        "name": "$pageleave",
                    },
                ],
            },
            ["1"],
        )

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_event_filter_with_group_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        session_id = f"test_event_filter_with_group_filter-ONE-{uuid4()}"
        different_group_session = f"test_event_filter_with_group_filter-TWO-{uuid4()}"

        produce_replay_summary(
            distinct_id="user",
            session_id=session_id,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.pk,
        )
        produce_replay_summary(
            distinct_id="user",
            session_id=different_group_session,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.pk,
        )

        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="project", group_type_index=0
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="project:1",
            properties={"name": "project one"},
        )

        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=1
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"name": "org one"},
        )

        create_event(
            distinct_id="user",
            timestamp=self.an_hour_ago,
            team=self.team,
            event_name="$pageview",
            properties={
                "$session_id": session_id,
                "$window_id": "1",
                "$group_1": "org:1",
            },
        )
        create_event(
            distinct_id="user",
            timestamp=self.an_hour_ago,
            team=self.team,
            event_name="$pageview",
            properties={
                "$session_id": different_group_session,
                "$window_id": "1",
                "$group_0": "project:1",
            },
        )

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "properties": [
                            {
                                "key": "name",
                                "value": ["org one"],
                                "operator": "exact",
                                "type": "group",
                                "group_type_index": 1,
                            }
                        ],
                    }
                ],
            },
            [session_id],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "name",
                        "value": ["org one"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 1,
                    }
                ],
            },
            [session_id],
        )

        self._assert_query_matches_session_ids(
            {
                "properties": [
                    {
                        "key": "name",
                        "value": ["org one"],
                        "operator": "exact",
                        "type": "group",
                        "group_type_index": 2,
                    }
                ],
            },
            [],
        )

    def test_all_filters_at_once(self):
        three_user_ids = [str(uuid4()) for _ in range(3)]
        target_session_id = f"test_all_filters_at_once-{str(uuid4())}"

        p = Person.objects.create(
            team=self.team,
            distinct_ids=[three_user_ids[0], three_user_ids[1]],
            properties={"email": "bla"},
        )
        custom_event_action = self.create_action(name="custom-event")

        produce_replay_summary(
            distinct_id=three_user_ids[0],
            session_id=target_session_id,
            first_timestamp=(self.an_hour_ago - relativedelta(days=3)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            # does not match because of user distinct id
            distinct_id=three_user_ids[2],
            session_id=target_session_id,
            first_timestamp=(self.an_hour_ago - relativedelta(days=3)),
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id=three_user_ids[0],
            timestamp=self.an_hour_ago - relativedelta(days=3),
            properties={"$session_id": target_session_id},
        )
        create_event(
            team=self.team,
            distinct_id=three_user_ids[0],
            timestamp=self.an_hour_ago - relativedelta(days=3),
            event_name="custom-event",
            properties={"$browser": "Chrome", "$session_id": target_session_id},
        )
        produce_replay_summary(
            distinct_id=three_user_ids[1],
            session_id=target_session_id,
            first_timestamp=(self.an_hour_ago - relativedelta(days=3) + relativedelta(hours=6)),
            team_id=self.team.id,
        )
        produce_replay_summary(
            distinct_id=three_user_ids[1],
            # does not match because of session id
            session_id=str(uuid4()),
            first_timestamp=(self.an_hour_ago - relativedelta(days=3) + relativedelta(hours=6)),
            team_id=self.team.id,
        )

        flush_persons_and_events()

        self._assert_query_matches_session_ids(
            {
                "person_uuid": str(p.uuid),
                "date_to": (self.an_hour_ago + relativedelta(days=3)).strftime("%Y-%m-%d"),
                "date_from": (self.an_hour_ago - relativedelta(days=10)).strftime("%Y-%m-%d"),
                "having_predicates": '[{"type":"recording","key":"duration","value":60,"operator":"gt"}]',
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "actions": [
                    {
                        "id": custom_event_action.id,
                        "type": "actions",
                        "order": 1,
                        "name": "custom-event",
                    }
                ],
            },
            [target_session_id],
        )

    @snapshot_clickhouse_queries
    def test_operand_or_event_filters(self):
        user = "test_operand_or_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "test@posthog.com"})

        second_user = "test_operand_or_filter-second_user"
        Person.objects.create(team=self.team, distinct_ids=[second_user], properties={"email": "david@posthog.com"})

        session_id_one = "session_id_one"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago + relativedelta(seconds=10),
            properties={"$session_id": session_id_one},
        )

        session_id_two = "session_id_two"
        produce_replay_summary(
            distinct_id=second_user,
            session_id=session_id_two,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago + relativedelta(seconds=10),
            event_name="custom_event",
            properties={"$session_id": session_id_two},
        )

        session_id_three = "session_id_three"
        produce_replay_summary(
            distinct_id=second_user,
            session_id=session_id_three,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "custom_event",
                        "type": "events",
                        "order": 0,
                        "name": "custom_event",
                    },
                ],
                "operand": "AND",
            },
            [],
        )

        self._assert_query_matches_session_ids(
            {
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    },
                    {
                        "id": "custom_event",
                        "type": "events",
                        "order": 0,
                        "name": "custom_event",
                    },
                ],
                "operand": "OR",
            },
            [session_id_two, session_id_one],
        )

    @parameterized.expand(
        [
            # Case 1: Neither has WARN and message "random"
            (
                '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "AND",
                0,
                [],
            ),
            # Case 2: AND only matches one recording
            (
                '[{"key": "level", "value": ["info"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "AND",
                1,
                ["both_log_filters"],
            ),
            # Case 3: Only one is WARN level
            (
                '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}]',
                "AND",
                1,
                ["one_log_filter"],
            ),
            # Case 4: Only one has message "random"
            (
                '[{"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "AND",
                1,
                ["both_log_filters"],
            ),
            # Case 5: OR matches both
            (
                '[{"key": "level", "value": ["warn"], "operator": "exact", "type": "log_entry"}, {"key": "message", "value": "random", "operator": "exact", "type": "log_entry"}]',
                "OR",
                2,
                ["both_log_filters", "one_log_filter"],
            ),
        ]
    )
    @snapshot_clickhouse_queries
    def test_operand_or_filters(
        self,
        console_log_filters: str,
        operand: Literal["AND", "OR"],
        expected_count: int,
        expected_session_ids: list[str],
    ) -> None:
        user = "test_operand_or_filter-user"
        Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        session_with_both_log_filters = "both_log_filters"
        produce_replay_summary(
            distinct_id="user",
            session_id=session_with_both_log_filters,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_log_count=1,
            log_messages={"info": ["random"]},
        )

        session_with_one_log_filter = "one_log_filter"
        produce_replay_summary(
            distinct_id="user",
            session_id=session_with_one_log_filter,
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            console_warn_count=1,
            log_messages={"warn": ["warn"]},
        )

        self._assert_query_matches_session_ids(
            {"console_log_filters": console_log_filters, "operand": operand}, expected_session_ids
        )

    @snapshot_clickhouse_queries
    def test_operand_or_mandatory_filters(self):
        user = "test_operand_or_filter-user"
        person = Person.objects.create(team=self.team, distinct_ids=[user], properties={"email": "bla"})

        second_user = "test_operand_or_filter-second_user"
        second_person = Person.objects.create(team=self.team, distinct_ids=[second_user], properties={"email": "bla"})

        session_id_one = "session_id_one"
        produce_replay_summary(
            distinct_id=user,
            session_id=session_id_one,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )
        create_event(
            team=self.team,
            distinct_id=user,
            timestamp=self.an_hour_ago + relativedelta(seconds=10),
            properties={"$session_id": session_id_one},
        )

        session_id_two = "session_id_two"
        produce_replay_summary(
            distinct_id=second_user,
            session_id=session_id_two,
            first_timestamp=self.an_hour_ago,
            last_timestamp=(self.an_hour_ago + relativedelta(seconds=30)),
            team_id=self.team.id,
        )

        # person or event filter -> person matches, event matches -> returns session
        self._assert_query_matches_session_ids(
            {
                "person_uuid": str(person.uuid),
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "operand": "OR",
            },
            [session_id_one],
        )

        # person or event filter -> person does not match, event matches -> does not return session
        self._assert_query_matches_session_ids(
            {
                "person_uuid": str(second_person.uuid),
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                    }
                ],
                "operand": "OR",
            },
            [],
        )
