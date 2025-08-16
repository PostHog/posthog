from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from parameterized import parameterized

from posthog.models import Person, GroupTypeMapping
from posthog.models.group.util import create_group
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.queries.test.listing_recordings.base_test_session_recordings_list import (
    BaseTestSessionRecordingsList,
)
from posthog.test.base import snapshot_clickhouse_queries, _create_event, flush_persons_and_events


@freeze_time("2020-01-01T13:46:23")
class TestSessionRecordingsListByGroupProperties(BaseTestSessionRecordingsList):
    @parameterized.expand(
        [
            [
                "group type index 1 match",
                # group type index 1 is the company group
                # it can only match session 2
                # and only with the property "another" with value "value"
                {"key": "another", "value": ["value"], "operator": "exact", "type": "group", "group_type_index": 1},
                ["session_id_two"],
            ],
            [
                "group type index 1 no match with right key and wrong value",
                # group type index 1 is the company group
                # it can only match session 2
                # and only with the property "another" with value "value"
                {
                    "key": "another",
                    "value": ["difference"],
                    "operator": "exact",
                    "type": "group",
                    "group_type_index": 1,
                },
                [],
            ],
            [
                "group type index 1 no match with wrong key right value",
                # group type index 1 is the company group
                # it can only match session 2
                # and only with the property "another" with value "value"
                {
                    "key": "difference",
                    "value": ["value"],
                    "operator": "exact",
                    "type": "group",
                    "group_type_index": 1,
                },
                [],
            ],
            [
                "group type index 0 match",
                # group type index 0 is the organization group
                # it can only match session 1
                # and only with the property "industry" with value "finance"
                {
                    "key": "industry",
                    "value": ["finance"],
                    "operator": "exact",
                    "type": "group",
                    "group_type_index": 0,
                },
                ["session_id_one"],
            ],
            [
                "no match for right key wrong value group text index 0 ",
                # group type index 0 is the organization group
                # it can only match session 1
                # and only with the property "industry" with value "finance"
                {
                    "key": "industry",
                    "value": ["difference"],
                    "operator": "exact",
                    "type": "group",
                    "group_type_index": 0,
                },
                [],
            ],
            [
                "no match for wrong key group type index 0",
                # group type index 0 is the organization group
                # it can only match session 1
                # and only with the property "industry" with value "finance"
                {
                    "key": "difference",
                    "value": ["finance"],
                    "operator": "exact",
                    "type": "group",
                    "group_type_index": 0,
                },
                [],
            ],
        ]
    )
    @snapshot_clickhouse_queries
    def test_filter_with_group_properties(
        self, _name: str, properties_query: dict, expected_sessions: list[str]
    ) -> None:
        # there is one person
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"$browser": "test"})

        # there are two groups
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )
        # each has an instance with properties
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"another": "value"},
        )
        # there are events in session 1 matching org5
        session_ids = {
            "session_id_one": str(uuid7()),
            "session_id_two": str(uuid7()),
        }
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            session_id=session_ids["session_id_one"],
            timestamp="2019-12-30T12:00:00Z",
            properties={"$group_0": "org:5", "$group_1": "company:12", "$session_id": session_ids["session_id_one"]},
        )
        # there are events in session 2 matching company:1
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            session_id=session_ids["session_id_two"],
            timestamp="2019-12-30T12:00:00Z",
            # without events
            properties={"$group_0": "org:40", "$group_1": "company:1", "$session_id": session_ids["session_id_two"]},
        )

        produce_replay_summary(
            distinct_id="p1",
            session_id=session_ids["session_id_one"],
            first_timestamp=self.an_hour_ago,
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )

        produce_replay_summary(
            distinct_id="p1",
            session_id=session_ids["session_id_two"],
            first_timestamp=self.an_hour_ago + relativedelta(seconds=30),
            team_id=self.team.id,
            ensure_analytics_event_in_session=False,
        )
        flush_persons_and_events()

        self.assert_query_matches_session_ids(
            {"properties": [properties_query]},
            [session_ids[k] for k in expected_sessions],
        )
