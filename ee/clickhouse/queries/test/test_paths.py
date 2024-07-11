from datetime import timedelta
from unittest.mock import MagicMock
from uuid import UUID

from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from posthog.constants import (
    FUNNEL_PATH_AFTER_STEP,
    FUNNEL_PATH_BEFORE_STEP,
    FUNNEL_PATH_BETWEEN_STEPS,
    INSIGHT_FUNNELS,
)
from posthog.models.filters import Filter, PathFilter
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.instance_setting import override_instance_config
from posthog.queries.paths import Paths, PathsActors
from posthog.queries.paths.paths_event_query import PathEventQuery
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    snapshot_clickhouse_queries,
    create_person_id_override_by_distinct_id,
)
import uuid
from django.test import override_settings

ONE_MINUTE = 60_000  # 1 minute in milliseconds


class TestClickhousePaths(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:2",
            properties={},
        )

    def _get_people_at_path(
        self,
        filter,
        path_start=None,
        path_end=None,
        funnel_filter=None,
        path_dropoff=None,
    ):
        person_filter = filter.shallow_clone(
            {
                "path_start_key": path_start,
                "path_end_key": path_end,
                "path_dropoff_key": path_dropoff,
            }
        )
        _, serialized_actors, _ = PathsActors(person_filter, self.team, funnel_filter).get_actors()
        return [row["id"] for row in serialized_actors]

    @snapshot_clickhouse_queries
    def test_step_limit(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["fake"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/4"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:27:34",
            ),
        )

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(team=self.team, data={"step_limit": 2})
            response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response,
                [
                    {
                        "source": "1_/1",
                        "target": "2_/2",
                        "value": 1,
                        "average_conversion_time": ONE_MINUTE,
                    }
                ],
            )
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "1_/1", "2_/2"))
            self.assertEqual([], self._get_people_at_path(filter, "2_/2", "3_/3"))

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(team=self.team, data={"step_limit": 3})
            response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response,
                [
                    {
                        "source": "1_/1",
                        "target": "2_/2",
                        "value": 1,
                        "average_conversion_time": ONE_MINUTE,
                    },
                    {
                        "source": "2_/2",
                        "target": "3_/3",
                        "value": 1,
                        "average_conversion_time": 2 * ONE_MINUTE,
                    },
                ],
            )
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "2_/2", "3_/3"))

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = PathFilter(team=self.team, data={"step_limit": 4})
            response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response,
                [
                    {
                        "source": "1_/1",
                        "target": "2_/2",
                        "value": 1,
                        "average_conversion_time": ONE_MINUTE,
                    },
                    {
                        "source": "2_/2",
                        "target": "3_/3",
                        "value": 1,
                        "average_conversion_time": 2 * ONE_MINUTE,
                    },
                    {
                        "source": "3_/3",
                        "target": "4_/4",
                        "value": 1,
                        "average_conversion_time": 3 * ONE_MINUTE,
                    },
                ],
            )
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "1_/1", "2_/2"))
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "2_/2", "3_/3"))
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "3_/3", "4_/4"))

    @snapshot_clickhouse_queries
    @freeze_time("2023-05-23T11:00:00.000Z")
    def test_step_conversion_times(self):
        _create_person(team_id=self.team.pk, distinct_ids=["fake"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/4"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:27:34",
            ),
        )

        _create_person(team_id=self.team.pk, distinct_ids=["fake2"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="fake2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="fake2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:23:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="fake2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:27:34",
            ),
        )

        filter = PathFilter(
            team=self.team,
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "include_event_types": ["$pageview"],
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 2,
                    "average_conversion_time": 1.5 * ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 2,
                    "average_conversion_time": 3 * ONE_MINUTE,
                },
                {
                    "source": "3_/3",
                    "target": "4_/4",
                    "value": 1,
                    "average_conversion_time": 3 * ONE_MINUTE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_event_ordering(self):
        # this tests to make sure that paths don't get scrambled when there are several similar variations
        events = []
        for i in range(50):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            person_events = [
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                    properties={},
                ),
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:01:00",
                    properties={},
                ),
                _create_event(
                    event="step three",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:02:00",
                    properties={},
                ),
            ]
            events.extend(person_events)

            if i % 2 == 0:
                events.append(
                    _create_event(
                        event="step branch",
                        distinct_id=f"user_{i}",
                        team=self.team,
                        timestamp="2021-05-01 00:03:00",
                        properties={},
                    )
                )

        filter = PathFilter(
            team=self.team,
            data={
                "date_from": "2021-05-01",
                "date_to": "2021-05-03",
                "include_event_types": ["custom_event"],
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step two",
                    "value": 50,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_step two",
                    "target": "3_step three",
                    "value": 50,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_step three",
                    "target": "4_step branch",
                    "value": 25,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    def _create_sample_data_multiple_dropoffs(self, use_groups=False):
        events = []
        if use_groups:
            self._create_groups()

        for i in range(5):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            full_funnel = [
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                    properties={"$group_0": "org:5"} if use_groups else {},
                ),
                _create_event(
                    event="between_step_1_a",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:01:00",
                    properties={"$group_0": "org:5"} if use_groups else {},
                ),
                _create_event(
                    event="between_step_1_b",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:02:00",
                    properties={"$group_0": "org:5"} if use_groups else {},
                ),
                _create_event(
                    event="between_step_1_c",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:03:00",
                    properties={"$group_0": "org:5"} if use_groups else {},
                ),
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:04:00",
                    properties={"$group_0": "org:5"} if use_groups else {},
                ),
                _create_event(
                    event="step three",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:05:00",
                    properties={"$group_0": "org:5"} if use_groups else {},
                ),
            ]
            events.extend(full_funnel)

        for i in range(5, 15):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            two_step_funnel = [
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                    properties={},
                ),
                _create_event(
                    event="between_step_1_a",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:01:00",
                    properties={},
                ),
                _create_event(
                    event="between_step_1_b",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:02:00",
                    properties={},
                ),
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:03:00",
                    properties={},
                ),
                _create_event(
                    event="between_step_2_a",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:04:20",
                    properties={},
                ),
                _create_event(
                    event="between_step_2_b",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:05:40",
                    properties={},
                ),
            ]
            events.extend(two_step_funnel)

        for i in range(15, 35):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            funnel_branching = [
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                    properties={"$group_0": "org:6"} if use_groups else {},
                ),
                _create_event(
                    event="step dropoff1",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:01:00",
                    properties={"$group_0": "org:6"} if use_groups else {},
                ),
                _create_event(
                    event="step dropoff2",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:02:00",
                    properties={"$group_0": "org:6"} if use_groups else {},
                ),
            ]
            if i % 2 == 0:
                funnel_branching.append(
                    _create_event(
                        event="step branch",
                        distinct_id=f"user_{i}",
                        team=self.team,
                        timestamp="2021-05-01 00:03:00",
                        properties={"$group_0": "org:6"} if use_groups else {},
                    )
                )
            events.extend(funnel_branching)

    @snapshot_clickhouse_queries
    def test_wildcard_groups(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "path_groupings": ["between_step_1_*", "between_step_2_*", "step drop*"],
        }
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step drop*",
                    "value": 20,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                # when we group events for a single user, these effectively become duplicate events, and we choose the last event from
                # a list of duplicate events.
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_*",
                    "value": 15,
                    "average_conversion_time": (5 * 3 + 10 * 2)
                    * ONE_MINUTE
                    / 15,  # first 5 go till between_step_1_c, next 10 go till between_step_1_b
                },
                {
                    "source": "2_between_step_1_*",
                    "target": "3_step two",
                    "value": 15,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_step drop*",
                    "target": "3_step branch",
                    "value": 10,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "3_step two",
                    "target": "4_between_step_2_*",
                    "value": 10,
                    "average_conversion_time": 160000,
                },
                {
                    "source": "3_step two",
                    "target": "4_step three",
                    "value": 5,
                    "average_conversion_time": ONE_MINUTE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_team_path_cleaning_rules(self):
        _create_person(distinct_ids=[f"user_1"], team=self.team)
        _create_person(distinct_ids=[f"user_2"], team=self.team)
        _create_person(distinct_ids=[f"user_3"], team=self.team)

        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step3?key=value1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step3?key=value2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step3?key=value3"},
                }
            ),
        )

        self.team.path_cleaning_filters = [{"alias": "?<param>", "regex": "\\?(.*)"}]
        self.team.save()

        data = {
            "insight": INSIGHT_FUNNELS,
            "include_event_types": ["$pageview"],
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
        }
        path_filter = PathFilter(data=data, team=self.team)
        response_no_flag = Paths(team=self.team, filter=path_filter).run()

        self.assertNotEqual(
            response_no_flag,
            [
                {
                    "source": "1_test.com/step1",
                    "target": "2_test.com/step2",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_test.com/step2",
                    "target": "3_test.com/step3?<param>",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

        # data.update({"path_replacements": "true"})
        path_filter = path_filter.shallow_clone({"path_replacements": "true"})
        response = Paths(team=self.team, filter=path_filter).run()

        self.assertEqual(
            response,
            [
                {
                    "source": "1_test.com/step1",
                    "target": "2_test.com/step2",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_test.com/step2",
                    "target": "3_test.com/step3?<param>",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_team_and_local_path_cleaning_rules(self):
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2/5"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step2/5?key=value1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2/5"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step2/5?key=value2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2/5"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step2/5?key=value3"},
                }
            ),
        )

        _create_person(distinct_ids=[f"user_1"], team=self.team)

        _create_person(distinct_ids=[f"user_2"], team=self.team)

        _create_person(distinct_ids=[f"user_3"], team=self.team)

        correct_response = [
            {
                "source": "1_test.com/step1",
                "target": "2_test.com/step2/<id>",
                "value": 3,
                "average_conversion_time": 60000.0,
            },
            {
                "source": "2_test.com/step2/<id>",
                "target": "3_test.com/step2/<id><param>",
                "value": 3,
                "average_conversion_time": 60000.0,
            },
        ]

        self.team.path_cleaning_filters = [
            {"alias": "?<param>", "regex": "\\?(.*)"},
            {"alias": "/<id>", "regex": "/\\d+(/|\\?)?"},
        ]
        self.team.save()

        data = {
            "insight": INSIGHT_FUNNELS,
            "include_event_types": ["$pageview"],
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "path_replacements": True,
        }
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter).run()
        self.assertEqual(response, correct_response)

        self.team.path_cleaning_filters = [{"alias": "?<param>", "regex": "\\?(.*)"}]
        self.team.save()

        data.update({"local_path_cleaning_filters": [{"alias": "/<id>", "regex": "/\\d+(/|\\?)?"}]})
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter).run()
        self.assertEqual(response, correct_response)

        # overriding team filters
        data.update(
            {
                "path_replacements": False,
                "local_path_cleaning_filters": [
                    {"alias": "?<param>", "regex": "\\?(.*)"},
                    {"alias": "/<id>", "regex": "/\\d+(/|\\?)?"},
                ],
            }
        )
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter).run()
        self.assertEqual(response, correct_response)

    @snapshot_clickhouse_queries
    @freeze_time("2023-05-23T11:00:00.000Z")
    def test_path_cleaning_rules_with_wildcard_groups(self):
        _create_person(distinct_ids=[f"user_1"], team=self.team)
        _create_person(distinct_ids=[f"user_2"], team=self.team)
        _create_person(distinct_ids=[f"user_3"], team=self.team)

        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1/foo"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_1",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step3?key=value1"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1/bar"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_2",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step3?key=value2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                    "properties": {"$current_url": "test.com/step1/baz"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:01:00",
                    "properties": {"$current_url": "test.com/step2"},
                }
            ),
        )
        (
            _create_event(
                **{
                    "event": "$pageview",
                    "distinct_id": f"user_3",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:02:00",
                    "properties": {"$current_url": "test.com/step3?key=value3"},
                }
            ),
        )

        data = {
            "insight": INSIGHT_FUNNELS,
            "include_event_types": ["$pageview"],
            "path_groupings": ["/step1"],
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "local_path_cleaning_filters": [{"alias": "?<param>", "regex": "\\?(.*)"}],
            "start_point": "/step1",
        }
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter).run()

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/step1",
                    "target": "2_test.com/step2",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_test.com/step2",
                    "target": "3_test.com/step3?<param>",
                    "value": 3,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_by_funnel_after_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": -2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data, team=self.team)
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step dropoff1",
                    "value": 20,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_step dropoff1",
                    "target": "3_step dropoff2",
                    "value": 20,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_step dropoff2",
                    "target": "4_step branch",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
            ],
        )
        self.assertEqual(
            20,
            len(self._get_people_at_path(path_filter, "1_step one", "2_step dropoff1", funnel_filter)),
        )
        self.assertEqual(
            20,
            len(self._get_people_at_path(path_filter, "2_step dropoff1", "3_step dropoff2", funnel_filter)),
        )
        self.assertEqual(
            10,
            len(self._get_people_at_path(path_filter, "3_step dropoff2", "4_step branch", funnel_filter)),
        )
        self.assertEqual(
            0,
            len(self._get_people_at_path(path_filter, "4_step branch", "3_step dropoff2", funnel_filter)),
        )

    @snapshot_clickhouse_queries
    def test_by_funnel_after_dropoff_with_group_filter(self):
        # complex case, joins funnel_actors and groups
        self._create_sample_data_multiple_dropoffs(use_groups=True)
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": -2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data, team=self.team)
        # passing group properties to funnel filter defeats purpose of test
        path_filter = PathFilter(data=data, team=self.team).shallow_clone(
            {
                "properties": [
                    {
                        "key": "industry",
                        "value": "technology",
                        "type": "group",
                        "group_type_index": 0,
                    }
                ]
            }
        )
        response = Paths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step dropoff1",
                    "value": 20,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_step dropoff1",
                    "target": "3_step dropoff2",
                    "value": 20,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_step dropoff2",
                    "target": "4_step branch",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
            ],
        )
        self.assertEqual(
            20,
            len(self._get_people_at_path(path_filter, "1_step one", "2_step dropoff1", funnel_filter)),
        )
        self.assertEqual(
            20,
            len(self._get_people_at_path(path_filter, "2_step dropoff1", "3_step dropoff2", funnel_filter)),
        )
        self.assertEqual(
            10,
            len(self._get_people_at_path(path_filter, "3_step dropoff2", "4_step branch", funnel_filter)),
        )
        self.assertEqual(
            0,
            len(self._get_people_at_path(path_filter, "4_step branch", "3_step dropoff2", funnel_filter)),
        )

    def test_by_funnel_after_step_respects_conversion_window(self):
        # note events happen after 1 day
        events = []
        for i in range(5):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            events.extend(
                [
                    _create_event(
                        **{
                            "event": "step one",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-01 00:00:00",
                            "properties": {},
                        }
                    ),
                    _create_event(
                        **{
                            "event": "between_step_1_a",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-02 00:00:00",
                            "properties": {},
                        }
                    ),
                    _create_event(
                        **{
                            "event": "between_step_1_b",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-03 00:00:00",
                            "properties": {},
                        }
                    ),
                    _create_event(
                        **{
                            "event": "between_step_1_c",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-04 00:00:00",
                            "properties": {},
                        }
                    ),
                    _create_event(
                        **{
                            "event": "step two",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-05 00:00:00",
                            "properties": {},
                        }
                    ),
                    _create_event(
                        **{
                            "event": "step three",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-06 00:00:00",
                            "properties": {},
                        }
                    ),
                ]
            )
        for i in range(15, 35):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            events.extend(
                [
                    _create_event(
                        **{
                            "event": "step one",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-01 00:00:00",
                            "properties": {},
                        }
                    ),
                    _create_event(
                        **{
                            "event": "step dropoff1",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-02 00:00:00",
                            "properties": {},
                        }
                    ),
                    _create_event(
                        **{
                            "event": "step dropoff2",
                            "distinct_id": f"user_{i}",
                            "team": self.team,
                            "timestamp": "2021-05-03 00:00:00",
                            "properties": {},
                        }
                    ),
                ]
            )
            if i % 2 == 0:
                events.extend(
                    [
                        _create_event(
                            **{
                                "event": "step branch",
                                "distinct_id": f"user_{i}",
                                "team": self.team,
                                "timestamp": "2021-05-04 00:00:00",
                                "properties": {},
                            }
                        )
                    ]
                )

        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": -2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data, team=self.team)
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step dropoff1",
                    "value": 20,
                    "average_conversion_time": ONE_MINUTE * 60 * 24,
                },
                {
                    "source": "2_step dropoff1",
                    "target": "3_step dropoff2",
                    "value": 20,
                    "average_conversion_time": ONE_MINUTE * 60 * 24,
                },
                {
                    "source": "3_step dropoff2",
                    "target": "4_step branch",
                    "value": 10,
                    "average_conversion_time": ONE_MINUTE * 60 * 24,
                },
            ],
        )
        self.assertEqual(
            20,
            len(self._get_people_at_path(path_filter, "1_step one", "2_step dropoff1", funnel_filter)),
        )
        self.assertEqual(
            20,
            len(self._get_people_at_path(path_filter, "2_step dropoff1", "3_step dropoff2", funnel_filter)),
        )
        self.assertEqual(
            10,
            len(self._get_people_at_path(path_filter, "3_step dropoff2", "4_step branch", funnel_filter)),
        )
        self.assertEqual(
            0,
            len(self._get_people_at_path(path_filter, "4_step branch", "3_step dropoff2", funnel_filter)),
        )

    @snapshot_clickhouse_queries
    def test_by_funnel_after_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data, team=self.team)
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step two",
                    "target": "2_between_step_2_a",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
                {
                    "source": "2_between_step_2_a",
                    "target": "3_between_step_2_b",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
                {
                    "source": "1_step two",
                    "target": "2_step three",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_by_funnel_after_step_limit(self):
        self._create_sample_data_multiple_dropoffs()
        events = []
        # add more than 100. Previously, the funnel limit at 100 was stopping all users from showing up
        for i in range(100, 200):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            person_events = [
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                    properties={},
                ),
                _create_event(
                    event="between_step_1_a",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:01:00",
                    properties={},
                ),
                _create_event(
                    event="between_step_1_b",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:02:00",
                    properties={},
                ),
                _create_event(
                    event="between_step_1_c",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:03:00",
                    properties={},
                ),
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:04:00",
                    properties={},
                ),
                _create_event(
                    event="step three",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:05:00",
                    properties={},
                ),
            ]
            events.extend(person_events)

        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_AFTER_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data, team=self.team)
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step two",
                    "target": "2_step three",
                    "value": 105,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "1_step two",
                    "target": "2_between_step_2_a",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
                {
                    "source": "2_between_step_2_a",
                    "target": "3_between_step_2_b",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_by_funnel_before_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_BEFORE_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": -3,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data, team=self.team)
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_a",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_between_step_1_a",
                    "target": "3_between_step_1_b",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_step two",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_step two",
                    "target": "5_between_step_2_a",
                    "value": 10,
                    "average_conversion_time": 80000.0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_by_funnel_before_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_BEFORE_STEP,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data, team=self.team)
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_a",
                    "value": 15,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_between_step_1_a",
                    "target": "3_between_step_1_b",
                    "value": 15,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_step two",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_between_step_1_c",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_between_step_1_c",
                    "target": "5_step two",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_by_funnel_between_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_paths": FUNNEL_PATH_BETWEEN_STEPS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_interval": 7,
            "funnel_window_interval_unit": "day",
            "funnel_step": 2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        funnel_filter = Filter(data=data, team=self.team)
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter, funnel_filter=funnel_filter).run()
        self.assertEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_a",
                    "value": 15,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_between_step_1_a",
                    "target": "3_between_step_1_b",
                    "value": 15,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_step two",
                    "value": 10,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_between_step_1_b",
                    "target": "4_between_step_1_c",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_between_step_1_c",
                    "target": "5_step two",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
            ],
        )
        self.assertEqual(
            15,
            len(self._get_people_at_path(path_filter, "1_step one", "2_between_step_1_a", funnel_filter)),
        )
        self.assertEqual(
            15,
            len(
                self._get_people_at_path(
                    path_filter,
                    "2_between_step_1_a",
                    "3_between_step_1_b",
                    funnel_filter,
                )
            ),
        )
        self.assertEqual(
            10,
            len(self._get_people_at_path(path_filter, "3_between_step_1_b", "4_step two", funnel_filter)),
        )
        self.assertEqual(
            5,
            len(
                self._get_people_at_path(
                    path_filter,
                    "3_between_step_1_b",
                    "4_between_step_1_c",
                    funnel_filter,
                )
            ),
        )
        self.assertEqual(
            5,
            len(self._get_people_at_path(path_filter, "4_between_step_1_c", "5_step two", funnel_filter)),
        )

    @also_test_with_materialized_columns(["$current_url", "$screen_name"])
    @snapshot_clickhouse_queries
    def test_end(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person_1"])
        p1 = [
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            ),
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            ),
            _create_event(
                properties={"$current_url": "/3/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:03:00",
            ),
            _create_event(
                properties={"$current_url": "/4/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:04:00",
            ),
            _create_event(
                properties={"$current_url": "/5"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:05:00",
            ),
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:06:00",
            ),
            _create_event(
                properties={"$current_url": "/after/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:07:00",
            ),
        ]

        _create_person(team_id=self.team.pk, distinct_ids=["person_2"])
        p2 = [
            _create_event(
                properties={"$current_url": "/5"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            ),
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            ),
        ]

        _create_person(team_id=self.team.pk, distinct_ids=["person_3"])
        p3 = [
            _create_event(
                properties={"$current_url": "/3/"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            ),
            _create_event(
                properties={"$current_url": "/4"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            ),
            _create_event(
                properties={"$current_url": "/about/"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:03:00",
            ),
            _create_event(
                properties={"$current_url": "/after"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:04:00",
            ),
        ]

        _ = [*p1, *p2, *p3]

        filter = PathFilter(
            team=self.team,
            data={
                "path_type": "$pageview",
                "end_point": "/about",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {
                    "source": "1_/2",
                    "target": "2_/3",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "1_/3",
                    "target": "2_/4",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "1_/5",
                    "target": "2_/about",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_/3",
                    "target": "3_/4",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_/4",
                    "target": "3_/about",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_/4",
                    "target": "4_/5",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_/5",
                    "target": "5_/about",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

        # ensure trailing slashes don't change results
        filter = PathFilter(
            team=self.team,
            data={
                "path_type": "$pageview",
                "end_point": "/about/",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {
                    "source": "1_/2",
                    "target": "2_/3",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "1_/3",
                    "target": "2_/4",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "1_/5",
                    "target": "2_/about",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_/3",
                    "target": "3_/4",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_/4",
                    "target": "3_/about",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_/4",
                    "target": "4_/5",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_/5",
                    "target": "5_/about",
                    "value": 1,
                    "average_conversion_time": 60000.0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    @freeze_time("2023-05-23T11:00:00.000Z")
    def test_event_inclusion_exclusion_filters(self):
        # P1 for pageview event
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        p1 = [
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$current_url": "/2/"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        # P2 for screen event
        _create_person(team_id=self.team.pk, distinct_ids=["p2"])
        p2 = [
            _create_event(
                properties={"$screen_name": "/screen1"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$screen_name": "/screen2"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$screen_name": "/screen3"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        # P3 for custom event
        _create_person(team_id=self.team.pk, distinct_ids=["p3"])
        p3 = [
            _create_event(
                distinct_id="p3",
                event="/custom1",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                distinct_id="p3",
                event="/custom2",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                distinct_id="p3",
                event="/custom3",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        _ = [*p1, *p2, *p3]

        filter = PathFilter(
            team=self.team,
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "include_event_types": ["$pageview"],
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone({"include_event_types": ["$screen"]})
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/screen1",
                    "target": "2_/screen2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/screen2",
                    "target": "3_/screen3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone({"include_event_types": ["custom_event"]})
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/custom1",
                    "target": "2_/custom2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/custom2",
                    "target": "3_/custom3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone(
            {
                "include_event_types": [],
                "include_custom_events": ["/custom1", "/custom2"],
            }
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/custom1",
                    "target": "2_/custom2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                }
            ],
        )

        filter = filter.shallow_clone({"include_event_types": [], "include_custom_events": ["/custom3", "blah"]})
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(response, [])

        filter = filter.shallow_clone(
            {
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "include_custom_events": [],
            }
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "1_/custom1",
                    "target": "2_/custom2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "1_/screen1",
                    "target": "2_/screen2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "2_/custom2",
                    "target": "3_/custom3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "2_/screen2",
                    "target": "3_/screen3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone(
            {
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "include_custom_events": [],
                "exclude_events": ["/custom1", "/1", "/2", "/3"],
            }
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {
                    "source": "1_/custom2",
                    "target": "2_/custom3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "1_/screen1",
                    "target": "2_/screen2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/screen2",
                    "target": "3_/screen3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    @freeze_time("2023-05-23T11:00:00.000Z")
    def test_event_exclusion_filters_with_wildcard_groups(self):
        # P1 for pageview event /2/bar/1/foo
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        p1 = [
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$current_url": "/2/bar/1/foo"},  # regex matches, despite beginning with `/2/`
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        # P2 for pageview event /bar/2/foo
        _create_person(team_id=self.team.pk, distinct_ids=["p2"])
        p2 = [
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$current_url": "/bar/2/foo"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        # P3 for pageview event /bar/3/foo
        _create_person(team_id=self.team.pk, distinct_ids=["p3"])
        p3 = [
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p3",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$current_url": "/bar/33/foo"},
                distinct_id="p3",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p3",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        _ = [*p1, *p2, *p3]

        filter = PathFilter(
            team=self.team,
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "exclude_events": ["/bar/*/foo"],
                "include_event_types": ["$pageview"],
                "path_groupings": ["/bar/*/foo"],
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/3",
                    "value": 3,
                    "average_conversion_time": 3 * ONE_MINUTE,
                }
            ],
        )

        filter = filter.shallow_clone({"path_groupings": ["/xxx/invalid/*"]})
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(len(response), 6)

    def test_event_inclusion_exclusion_filters_across_single_person(self):
        # P1 for pageview event, screen event, and custom event all together
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/screen1"},
                distinct_id="p1",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:25:34",
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/screen2"},
                distinct_id="p1",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:26:34",
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/screen3"},
                distinct_id="p1",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:28:34",
            ),
        )
        (
            _create_event(
                distinct_id="p1",
                event="/custom1",
                team=self.team,
                timestamp="2012-01-01 03:29:34",
            ),
        )
        (
            _create_event(
                distinct_id="p1",
                event="/custom2",
                team=self.team,
                timestamp="2012-01-01 03:30:34",
            ),
        )
        (
            _create_event(
                distinct_id="p1",
                event="/custom3",
                team=self.team,
                timestamp="2012-01-01 03:32:34",
            ),
        )

        filter = PathFilter(
            team=self.team, data={"step_limit": 10, "date_from": "2012-01-01"}
        )  # include everything, exclude nothing
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "3_/3",
                    "target": "4_/screen1",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "4_/screen1",
                    "target": "5_/screen2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "5_/screen2",
                    "target": "6_/screen3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "6_/screen3",
                    "target": "7_/custom1",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "7_/custom1",
                    "target": "8_/custom2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "8_/custom2",
                    "target": "9_/custom3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone({"include_event_types": ["$pageview", "$screen"]})
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "3_/3",
                    "target": "4_/screen1",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "4_/screen1",
                    "target": "5_/screen2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "5_/screen2",
                    "target": "6_/screen3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone(
            {
                "include_event_types": ["$pageview", "$screen"],
                "include_custom_events": ["/custom2"],
            }
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "3_/3",
                    "target": "4_/screen1",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "4_/screen1",
                    "target": "5_/screen2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "5_/screen2",
                    "target": "6_/screen3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "6_/screen3",
                    "target": "7_/custom2",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone(
            {
                "include_event_types": ["$pageview", "custom_event"],
                "include_custom_events": [],
                "exclude_events": ["/custom1", "/custom3"],
            }
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                {
                    "source": "3_/3",
                    "target": "4_/custom2",
                    "value": 1,
                    "average_conversion_time": 6 * ONE_MINUTE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    @freeze_time("2023-05-23T11:00:00.000Z")
    def test_respect_session_limits(self):
        _create_person(team_id=self.team.pk, distinct_ids=["fake"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-02 03:21:54",  # new day, new session
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2/"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-02 03:22:54",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-02 03:26:54",
            ),
        )

        filter = PathFilter(team=self.team, data={"date_from": "2012-01-01"})
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 2,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 2,
                    "average_conversion_time": 3 * ONE_MINUTE,
                },
            ],
        )

    def test_removes_duplicates(self):
        _create_person(team_id=self.team.pk, distinct_ids=["fake"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:54",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2/"},  # trailing slash should be removed
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:54",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="fake",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:54",
            ),
        )

        _create_person(team_id=self.team.pk, distinct_ids=["fake2"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="fake2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2/"},
                distinct_id="fake2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:23:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="fake2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:27:34",
            ),
        )

        filter = PathFilter(team=self.team, data={"date_from": "2012-01-01"})
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 2,
                    "average_conversion_time": 1.5 * ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 2,
                    "average_conversion_time": 3 * ONE_MINUTE,
                },
            ],
        )

    @also_test_with_materialized_columns(["$current_url", "$screen_name"])
    @snapshot_clickhouse_queries
    def test_start_and_end(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["person_1"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:03:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/4"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:04:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/5"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:05:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:06:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/after"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:07:00",
            ),
        )

        p2 = _create_person(team_id=self.team.pk, distinct_ids=["person_2"])

        (
            _create_event(
                properties={"$current_url": "/5"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            ),
        )

        _create_person(team_id=self.team.pk, distinct_ids=["person_3"])

        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/4"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:03:00",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/after"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:04:00",
            ),
        )

        filter = PathFilter(
            team=self.team,
            data={
                "path_type": "$pageview",
                "start_point": "/5",
                "end_point": "/about",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {
                    "source": "1_/5",
                    "target": "2_/about",
                    "value": 2,
                    "average_conversion_time": 60000.0,
                }
            ],
        )
        self.assertCountEqual(self._get_people_at_path(filter, "1_/5", "2_/about"), [p1.uuid, p2.uuid])

        # test aggregation for long paths
        filter = filter.shallow_clone({"start_point": "/2", "step_limit": 4})
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {
                    "source": "1_/2",
                    "target": "2_/3",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/3",
                    "target": "3_...",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "3_...",
                    "target": "4_/5",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "4_/5",
                    "target": "5_/about",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
            ],
        )
        self.assertCountEqual(self._get_people_at_path(filter, "3_...", "4_/5"), [p1.uuid])

    @snapshot_clickhouse_queries
    def test_properties_queried_using_path_filter(self):
        def should_query_list(filter) -> tuple[bool, bool]:
            path_query = PathEventQuery(filter, self.team)
            return (path_query._should_query_url(), path_query._should_query_screen())

        filter = PathFilter()
        self.assertEqual(should_query_list(filter), (True, True))

        filter = PathFilter({"include_event_types": ["$pageview"]})
        self.assertEqual(should_query_list(filter), (True, False))

        filter = PathFilter({"include_event_types": ["$screen"]})
        self.assertEqual(should_query_list(filter), (False, True))

        filter = filter.shallow_clone(
            {
                "include_event_types": [],
                "include_custom_events": ["/custom1", "/custom2"],
            }
        )
        self.assertEqual(should_query_list(filter), (False, False))

        filter = filter.shallow_clone(
            {
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "include_custom_events": [],
            }
        )
        self.assertEqual(should_query_list(filter), (True, True))

        filter = filter.shallow_clone(
            {
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "include_custom_events": [],
                "exclude_events": ["/custom1"],
            }
        )
        self.assertEqual(should_query_list(filter), (True, True))

        filter = filter.shallow_clone(
            {
                "include_event_types": [],
                "include_custom_events": [],
                "exclude_events": ["$pageview"],
            }
        )
        self.assertEqual(should_query_list(filter), (False, True))

    @snapshot_clickhouse_queries
    @freeze_time("2023-05-23T11:00:00.000Z")
    def test_wildcard_groups_across_people(self):
        # P1 for pageview event /2/bar/1/foo
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2/bar/1/foo"},  # regex matches, despite beginning with `/2/`
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )

        # P2 for pageview event /bar/2/foo
        _create_person(team_id=self.team.pk, distinct_ids=["p2"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/bar/2/foo"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )

        # P3 for pageview event /bar/3/foo
        _create_person(team_id=self.team.pk, distinct_ids=["p3"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p3",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/bar/33/foo"},
                distinct_id="p3",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p3",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )

        filter = PathFilter(
            team=self.team,
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "include_event_types": ["$pageview"],
                "path_groupings": ["/bar/*/foo"],
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/bar/*/foo",
                    "value": 3,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/bar/*/foo",
                    "target": "3_/3",
                    "value": 3,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    @freeze_time("2023-05-23T11:00:00.000Z")
    def test_wildcard_groups_evil_input(self):
        evil_string = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!"
        # P1 for pageview event /2/bar/1/foo
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])

        (
            _create_event(
                properties={"$current_url": evil_string},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2/bar/aaa"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )

        # P2 for pageview event /2/bar/2/foo
        _create_person(team_id=self.team.pk, distinct_ids=["p2"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2/3?q=1"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/3?q=1"},
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        )

        filter = PathFilter(
            team=self.team,
            data={
                "date_from": "2012-01-01",
                "include_event_types": ["$pageview"],
                "path_groupings": [
                    "(a+)+",
                    "[aaa|aaaa]+",
                    "1.*",
                    ".*",
                    "/3?q=1",
                    "/3*",
                ],
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/3*",
                    "value": 1,
                    "average_conversion_time": 3 * ONE_MINUTE,
                },
                {
                    "source": f"1_{evil_string}",
                    "target": "2_/2/bar/aaa",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2/bar/aaa",
                    "target": "3_/3*",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_person_dropoffs(self):
        events = []

        # 5 people do 2 events
        for i in range(5):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            two_step = [
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                    properties={},
                ),
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:04:00",
                    properties={},
                ),
            ]
            events.extend(two_step)

        # 10 people do 3 events
        for i in range(5, 15):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            three_step = [
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                    properties={},
                ),
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:04:00",
                    properties={},
                ),
                _create_event(
                    event="step three",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:05:00",
                    properties={},
                ),
            ]
            events.extend(three_step)

        # 20 people do 4 events
        for i in range(15, 35):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            four_step = [
                _create_event(
                    event="step one",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:00:00",
                    properties={},
                ),
                _create_event(
                    event="step two",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:04:00",
                    properties={},
                ),
                _create_event(
                    event="step three",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:05:00",
                    properties={},
                ),
                _create_event(
                    event="step four",
                    distinct_id=f"user_{i}",
                    team=self.team,
                    timestamp="2021-05-01 00:06:00",
                    properties={},
                ),
            ]
            events.extend(four_step)

        filter = PathFilter(
            team=self.team,
            data={
                "include_event_types": ["custom_event"],
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            },
        )
        self.assertEqual(5, len(self._get_people_at_path(filter, path_dropoff="2_step two")))  # 5 dropoff at step 2
        self.assertEqual(35, len(self._get_people_at_path(filter, path_end="2_step two")))  # 35 total reach step 2
        self.assertEqual(
            30, len(self._get_people_at_path(filter, path_start="2_step two"))
        )  # 30 total reach after step 2

        self.assertEqual(10, len(self._get_people_at_path(filter, path_dropoff="3_step three")))  # 10 dropoff at step 3
        self.assertEqual(30, len(self._get_people_at_path(filter, path_end="3_step three")))  # 30 total reach step 3
        self.assertEqual(
            20, len(self._get_people_at_path(filter, path_start="3_step three"))
        )  # 20 total reach after step 3

        self.assertEqual(20, len(self._get_people_at_path(filter, path_dropoff="4_step four")))  # 20 dropoff at step 4
        self.assertEqual(20, len(self._get_people_at_path(filter, path_end="4_step four")))  # 20 total reach step 4
        self.assertEqual(
            0, len(self._get_people_at_path(filter, path_start="4_step four"))
        )  # 0 total reach after step 4

    @snapshot_clickhouse_queries
    def test_start_dropping_orphaned_edges(self):
        events = []
        for i in range(5):
            # 5 people going through this route to increase weights
            _create_person(team_id=self.team.pk, distinct_ids=[f"person_{i}"])
            special_route = [
                _create_event(
                    properties={"$current_url": "/1"},
                    distinct_id=f"person_{i}",
                    event="$pageview",
                    team=self.team,
                    timestamp="2021-05-01 00:01:00",
                ),
                _create_event(
                    properties={"$current_url": "/2"},
                    distinct_id=f"person_{i}",
                    event="$pageview",
                    team=self.team,
                    timestamp="2021-05-01 00:02:00",
                ),
                _create_event(
                    properties={"$current_url": "/3"},
                    distinct_id=f"person_{i}",
                    event="$pageview",
                    team=self.team,
                    timestamp="2021-05-01 00:03:00",
                ),
                _create_event(
                    properties={"$current_url": "/4"},
                    distinct_id=f"person_{i}",
                    event="$pageview",
                    team=self.team,
                    timestamp="2021-05-01 00:04:00",
                ),
                _create_event(
                    properties={"$current_url": "/5"},
                    distinct_id=f"person_{i}",
                    event="$pageview",
                    team=self.team,
                    timestamp="2021-05-01 00:05:00",
                ),
                _create_event(
                    properties={"$current_url": "/about"},
                    distinct_id=f"person_{i}",
                    event="$pageview",
                    team=self.team,
                    timestamp="2021-05-01 00:06:00",
                ),
                _create_event(
                    properties={"$current_url": "/after"},
                    distinct_id=f"person_{i}",
                    event="$pageview",
                    team=self.team,
                    timestamp="2021-05-01 00:07:00",
                ),
            ]
            events.extend(special_route)

        _create_person(team_id=self.team.pk, distinct_ids=["person_r_2"])
        events_p2 = [
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="person_r_2",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            ),
            _create_event(
                properties={"$current_url": "/a"},
                distinct_id="person_r_2",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:30",
            ),
            _create_event(
                properties={"$current_url": "/x"},
                distinct_id="person_r_2",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            ),
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_r_2",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:03:00",
            ),
        ]
        events.extend(events_p2)

        _create_person(team_id=self.team.pk, distinct_ids=["person_r_3"])
        event_p3 = [
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="person_r_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:00",
            ),
            _create_event(
                properties={"$current_url": "/b"},
                distinct_id="person_r_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:01:30",
            ),
            _create_event(
                properties={"$current_url": "/x"},
                distinct_id="person_r_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:02:00",
            ),
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_r_3",
                event="$pageview",
                team=self.team,
                timestamp="2021-05-01 00:03:00",
            ),
        ]

        events.extend(event_p3)

        # /x -> /about has higher weight than /2 -> /a -> /x and /2 -> /b -> /x

        filter = PathFilter(
            team=self.team,
            data={
                "path_type": "$pageview",
                "start_point": "/2",
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "edge_limit": "6",
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
        self.assertEqual(
            response,
            [
                {
                    "source": "1_/2",
                    "target": "2_/3",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "2_/3",
                    "target": "3_/4",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "3_/4",
                    "target": "4_/5",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
                {
                    "source": "4_/5",
                    "target": "5_/about",
                    "value": 5,
                    "average_conversion_time": 60000.0,
                },
                # {'source': '3_/x', 'target': '4_/about', 'value': 2, 'average_conversion_time': 60000.0}, # gets deleted by validation since dangling
                {
                    "source": "1_/2",
                    "target": "2_/a",
                    "value": 1,
                    "average_conversion_time": 30000.0,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_wildcard_groups_and_min_edge_weight(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "min_edge_weight": 15,
            "path_groupings": ["between_step_1_*", "between_step_2_*", "step drop*"],
        }
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step drop*",
                    "value": 20,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                # when we group events for a single user, these effectively become duplicate events, and we choose the last event from
                # a list of duplicate events.
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_*",
                    "value": 15,
                    "average_conversion_time": (5 * 3 + 10 * 2)
                    * ONE_MINUTE
                    / 15,  # first 5 go till between_step_1_c, next 10 go till between_step_1_b
                },
                {
                    "source": "2_between_step_1_*",
                    "target": "3_step two",
                    "value": 15,
                    "average_conversion_time": ONE_MINUTE,
                },
            ],
        )

        path_filter = path_filter.shallow_clone({"edge_limit": 2})
        response = Paths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step drop*",
                    "value": 20,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                # when we group events for a single user, these effectively become duplicate events, and we choose the last event from
                # a list of duplicate events.
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_*",
                    "value": 15,
                    "average_conversion_time": (5 * 3 + 10 * 2)
                    * ONE_MINUTE
                    / 15,  # first 5 go till between_step_1_c, next 10 go till between_step_1_b
                },
            ],
        )

        path_filter = path_filter.shallow_clone({"edge_limit": 20, "max_edge_weight": 11, "min_edge_weight": 6})
        response = Paths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "2_step drop*",
                    "target": "3_step branch",
                    "value": 10,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "3_step two",
                    "target": "4_between_step_2_*",
                    "value": 10,
                    "average_conversion_time": 160000,
                },
            ],
        )

    # TODO: Delete this test when moved to person-on-events
    def test_groups_filtering(self):
        self._create_groups()
        # P1 for pageview event, org:5
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        p1 = [
            _create_event(
                properties={"$current_url": "/1", "$group_0": "org:5"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$current_url": "/2/", "$group_0": "org:5"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$current_url": "/3", "$group_0": "org:5"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        # P2 for screen event, org:6
        _create_person(team_id=self.team.pk, distinct_ids=["p2"])
        p2 = [
            _create_event(
                properties={"$screen_name": "/screen1", "$group_0": "org:6"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$screen_name": "/screen2", "$group_0": "org:6"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$screen_name": "/screen3", "$group_0": "org:6"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        # P3 for custom event, group_0 doesnt' exist, group_1 = company:1
        _create_person(team_id=self.team.pk, distinct_ids=["p3"])
        p3 = [
            _create_event(
                distinct_id="p3",
                event="/custom1",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
                properties={"$group_1": "company:1"},
            ),
            _create_event(
                distinct_id="p3",
                event="/custom2",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
                properties={"$group_1": "company:1"},
            ),
            _create_event(
                distinct_id="p3",
                event="/custom3",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
                properties={"$group_1": "company:1"},
            ),
        ]

        _ = [*p1, *p2, *p3]

        filter = PathFilter(
            team=self.team,
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "date_to": "2012-02-01",
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "properties": [
                    {
                        "key": "industry",
                        "value": "finance",
                        "type": "group",
                        "group_type_index": 0,
                    }
                ],
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone(
            {
                "properties": [
                    {
                        "key": "industry",
                        "value": "technology",
                        "type": "group",
                        "group_type_index": 0,
                    }
                ]
            }
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/screen1",
                    "target": "2_/screen2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/screen2",
                    "target": "3_/screen3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

        filter = filter.shallow_clone(
            {
                "properties": [
                    {
                        "key": "industry",
                        "value": "technology",
                        "type": "group",
                        "group_type_index": 1,
                    }
                ]
            }
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                {
                    "source": "1_/custom1",
                    "target": "2_/custom2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/custom2",
                    "target": "3_/custom3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_groups_filtering_person_on_events(self):
        self._create_groups()
        # P1 for pageview event, org:5
        _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        p1 = [
            _create_event(
                properties={"$current_url": "/1", "$group_0": "org:5"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$current_url": "/2/", "$group_0": "org:5"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$current_url": "/3", "$group_0": "org:5"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        # P2 for screen event, org:6
        _create_person(team_id=self.team.pk, distinct_ids=["p2"])
        p2 = [
            _create_event(
                properties={"$screen_name": "/screen1", "$group_0": "org:6"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
            ),
            _create_event(
                properties={"$screen_name": "/screen2", "$group_0": "org:6"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
            ),
            _create_event(
                properties={"$screen_name": "/screen3", "$group_0": "org:6"},
                distinct_id="p2",
                event="$screen",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
            ),
        ]

        # P3 for custom event, group_0 doesnt' exist, group_1 = company:1
        _create_person(team_id=self.team.pk, distinct_ids=["p3"])
        p3 = [
            _create_event(
                distinct_id="p3",
                event="/custom1",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
                properties={"$group_1": "company:1"},
            ),
            _create_event(
                distinct_id="p3",
                event="/custom2",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
                properties={"$group_1": "company:1"},
            ),
            _create_event(
                distinct_id="p3",
                event="/custom3",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
                properties={"$group_1": "company:1"},
            ),
        ]

        _ = [*p1, *p2, *p3]

        filter = PathFilter(
            team=self.team,
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "date_to": "2012-02-01",
                "include_event_types": ["$pageview", "$screen", "custom_event"],
                "properties": [
                    {
                        "key": "industry",
                        "value": "finance",
                        "type": "group",
                        "group_type_index": 0,
                    }
                ],
            },
        )
        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response,
                [
                    {
                        "source": "1_/1",
                        "target": "2_/2",
                        "value": 1,
                        "average_conversion_time": ONE_MINUTE,
                    },
                    {
                        "source": "2_/2",
                        "target": "3_/3",
                        "value": 1,
                        "average_conversion_time": 2 * ONE_MINUTE,
                    },
                ],
            )

            filter = filter.shallow_clone(
                {
                    "properties": [
                        {
                            "key": "industry",
                            "value": "technology",
                            "type": "group",
                            "group_type_index": 0,
                        }
                    ]
                }
            )
            response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response,
                [
                    {
                        "source": "1_/screen1",
                        "target": "2_/screen2",
                        "value": 1,
                        "average_conversion_time": ONE_MINUTE,
                    },
                    {
                        "source": "2_/screen2",
                        "target": "3_/screen3",
                        "value": 1,
                        "average_conversion_time": 2 * ONE_MINUTE,
                    },
                ],
            )

            filter = filter.shallow_clone(
                {
                    "properties": [
                        {
                            "key": "industry",
                            "value": "technology",
                            "type": "group",
                            "group_type_index": 1,
                        }
                    ]
                }
            )
            response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(
                response,
                [
                    {
                        "source": "1_/custom1",
                        "target": "2_/custom2",
                        "value": 1,
                        "average_conversion_time": ONE_MINUTE,
                    },
                    {
                        "source": "2_/custom2",
                        "target": "3_/custom3",
                        "value": 1,
                        "average_conversion_time": 2 * ONE_MINUTE,
                    },
                ],
            )

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    @snapshot_clickhouse_queries
    def test_person_on_events_v2(self):
        self._create_groups()
        # P1 for pageview event, org:5
        p1_person_id = str(uuid.uuid4())
        _create_person(team_id=self.team.pk, distinct_ids=["poev2_p1"])
        p1 = [
            _create_event(
                properties={"$current_url": "/1", "$group_0": "org:5"},
                distinct_id="poev2_p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
                person_id=p1_person_id,
            ),
            _create_event(
                properties={"$current_url": "/2/", "$group_0": "org:5"},
                distinct_id="poev2_p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
                person_id=p1_person_id,
            ),
            _create_event(
                properties={"$current_url": "/3", "$group_0": "org:5"},
                distinct_id="poev2_p1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
                person_id=p1_person_id,
            ),
        ]

        # P2 for screen event, org:6
        p2_person_id = str(uuid.uuid4())
        _create_person(team_id=self.team.pk, distinct_ids=["poev2_p2"])
        p2 = [
            _create_event(
                properties={"$current_url": "/1", "$group_0": "org:6"},
                distinct_id="poev2_p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:21:34",
                person_id=p2_person_id,
            ),
            _create_event(
                properties={"$current_url": "/2/", "$group_0": "org:6"},
                distinct_id="poev2_p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:22:34",
                person_id=p2_person_id,
            ),
            _create_event(
                properties={"$current_url": "/3", "$group_0": "org:6"},
                distinct_id="poev2_p2",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-01 03:24:34",
                person_id=p2_person_id,
            ),
        ]

        _ = [*p1, *p2]

        create_person_id_override_by_distinct_id("poev2_p1", "poev2_p2", self.team.pk)

        filter = PathFilter(
            team=self.team,
            data={
                "step_limit": 4,
                "date_from": "2012-01-01",
                "date_to": "2012-02-01",
                "include_event_types": ["$pageview", "$screen", "custom_event"],
            },
        )
        response = Paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

        self.assertEqual(
            response,
            [
                # we expect 1s for the "value"s because the two persons above are actually the same person
                # due to the override
                {
                    "source": "1_/1",
                    "target": "2_/2",
                    "value": 1,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_/2",
                    "target": "3_/3",
                    "value": 1,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
            ],
        )

    @freeze_time("2012-01-01T03:21:34.000Z")
    @snapshot_clickhouse_queries
    def test_recording(self):
        # User with 2 matching paths with recordings
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"])
        events = [
            _create_event(
                properties={
                    "$current_url": "/1",
                    "$session_id": "s1",
                    "$window_id": "w1",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="11111111-1111-1111-1111-111111111111",
            ),
            _create_event(
                properties={
                    "$current_url": "/2",
                    "$session_id": "s1",
                    "$window_id": "w1",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="21111111-1111-1111-1111-111111111111",
            ),
            _create_event(
                properties={
                    "$current_url": "/1",
                    "$session_id": "s2",
                    "$window_id": "w2",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="31111111-1111-1111-1111-111111111111",
            ),
            _create_event(
                properties={
                    "$current_url": "/2",
                    "$session_id": "s3",
                    "$window_id": "w3",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=32)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="41111111-1111-1111-1111-111111111111",
            ),
        ]
        timestamp = timezone.now()
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            distinct_id="p1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )
        timestamp1 = timezone.now()
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s3",
            distinct_id="p1",
            first_timestamp=timestamp1,
            last_timestamp=timestamp1,
        )

        # User with path matches, but no recordings
        p2 = _create_person(team_id=self.team.pk, distinct_ids=["p2"])
        events += [
            _create_event(
                properties={
                    "$current_url": "/1",
                    "$session_id": "s5",
                    "$window_id": "w1",
                },
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp=timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="51111111-1111-1111-1111-111111111111",
            ),
            _create_event(
                properties={
                    "$current_url": "/2",
                    "$session_id": "s5",
                    "$window_id": "w1",
                },
                distinct_id="p2",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="61111111-1111-1111-1111-111111111111",
            ),
        ]

        filter = PathFilter(
            team=self.team,
            data={
                "include_event_types": ["$pageview"],
                "date_from": "2012-01-01 00:00:00",
                "date_to": "2012-01-02 00:00:00",
                "path_end_key": "2_/2",
                "include_recordings": "true",
            },
        )
        _, serialized_actors, _ = PathsActors(filter, self.team).get_actors()
        self.assertCountEqual([p1.uuid, p2.uuid], [actor["id"] for actor in serialized_actors])
        matched_recordings = [actor["matched_recordings"] for actor in serialized_actors]

        self.assertCountEqual(
            [
                {
                    "session_id": "s3",
                    "events": [
                        {
                            "uuid": UUID("41111111-1111-1111-1111-111111111111"),
                            "timestamp": timezone.now() + timedelta(minutes=32),
                            "window_id": "w3",
                        }
                    ],
                },
                {
                    "session_id": "s1",
                    "events": [
                        {
                            "uuid": UUID("21111111-1111-1111-1111-111111111111"),
                            "timestamp": timezone.now() + timedelta(minutes=1),
                            "window_id": "w1",
                        }
                    ],
                },
            ],
            matched_recordings[0],
        )
        self.assertEqual([], matched_recordings[1])

    @snapshot_clickhouse_queries
    @freeze_time("2012-01-01T03:21:34.000Z")
    def test_recording_with_no_window_or_session_id(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"])

        (
            _create_event(
                properties={"$current_url": "/1"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="11111111-1111-1111-1111-111111111111",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/2"},
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="21111111-1111-1111-1111-111111111111",
            ),
        )

        filter = PathFilter(
            team=self.team,
            data={
                "include_event_types": ["$pageview"],
                "date_from": "2012-01-01 00:00:00",
                "date_to": "2012-01-02 00:00:00",
                "path_end_key": "2_/2",
                "include_recordings": "true",
            },
        )
        _, serialized_actors, _ = PathsActors(filter, self.team).get_actors()
        self.assertEqual([p1.uuid], [actor["id"] for actor in serialized_actors])
        self.assertEqual([[]], [actor["matched_recordings"] for actor in serialized_actors])

    @snapshot_clickhouse_queries
    @freeze_time("2012-01-01T03:21:34.000Z")
    def test_recording_with_start_and_end(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"])

        (
            _create_event(
                properties={
                    "$current_url": "/1",
                    "$session_id": "s1",
                    "$window_id": "w1",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="11111111-1111-1111-1111-111111111111",
            ),
        )
        (
            _create_event(
                properties={
                    "$current_url": "/2",
                    "$session_id": "s1",
                    "$window_id": "w1",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="21111111-1111-1111-1111-111111111111",
            ),
        )
        (
            _create_event(
                properties={
                    "$current_url": "/3",
                    "$session_id": "s1",
                    "$window_id": "w1",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="31111111-1111-1111-1111-111111111111",
            ),
        )

        timestamp = timezone.now()
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            distinct_id="p1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        filter = PathFilter(
            team=self.team,
            data={
                "include_event_types": ["$pageview"],
                "date_from": "2012-01-01 00:00:00",
                "date_to": "2012-01-02 00:00:00",
                "path_end_key": "2_/2",
                "start_point": "/1",
                "end_point": "/3",
                "include_recordings": "true",
            },
        )
        _, serialized_actors, _ = PathsActors(filter, self.team).get_actors()
        self.assertEqual([p1.uuid], [actor["id"] for actor in serialized_actors])
        self.assertEqual(
            [
                [
                    {
                        "session_id": "s1",
                        "events": [
                            {
                                "uuid": UUID("21111111-1111-1111-1111-111111111111"),
                                "timestamp": timezone.now() + timedelta(minutes=1),
                                "window_id": "w1",
                            }
                        ],
                    }
                ]
            ],
            [actor["matched_recordings"] for actor in serialized_actors],
        )

    @snapshot_clickhouse_queries
    @freeze_time("2012-01-01T03:21:34.000Z")
    def test_recording_for_dropoff(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["p1"])

        (
            _create_event(
                properties={
                    "$current_url": "/1",
                    "$session_id": "s1",
                    "$window_id": "w1",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="11111111-1111-1111-1111-111111111111",
            ),
        )
        (
            _create_event(
                properties={
                    "$current_url": "/2",
                    "$session_id": "s1",
                    "$window_id": "w1",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="21111111-1111-1111-1111-111111111111",
            ),
        )
        (
            _create_event(
                properties={
                    "$current_url": "/3",
                    "$session_id": "s1",
                    "$window_id": "w1",
                },
                distinct_id="p1",
                event="$pageview",
                team=self.team,
                timestamp=(timezone.now() + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.%f"),
                event_uuid="31111111-1111-1111-1111-111111111111",
            ),
        )

        timestamp = timezone.now()
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            distinct_id="p1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        # No matching events for dropoff
        filter = PathFilter(
            team=self.team,
            data={
                "include_event_types": ["$pageview"],
                "date_from": "2012-01-01 00:00:00",
                "date_to": "2012-01-02 00:00:00",
                "path_dropoff_key": "2_/2",
                "include_recordings": "true",
            },
        )
        _, serialized_actors, _ = PathsActors(filter, self.team).get_actors()
        self.assertEqual([], [actor["id"] for actor in serialized_actors])
        self.assertEqual([], [actor["matched_recordings"] for actor in serialized_actors])

        # Matching events for dropoff
        filter = PathFilter(
            team=self.team,
            data={
                "include_event_types": ["$pageview"],
                "date_from": "2012-01-01 00:00:00",
                "date_to": "2012-01-02 00:00:00",
                "path_dropoff_key": "3_/3",
                "include_recordings": "true",
            },
        )
        _, serialized_actors, _ = PathsActors(filter, self.team).get_actors()
        self.assertEqual([p1.uuid], [actor["id"] for actor in serialized_actors])
        self.assertEqual(
            [
                [
                    {
                        "session_id": "s1",
                        "events": [
                            {
                                "uuid": UUID("31111111-1111-1111-1111-111111111111"),
                                "timestamp": timezone.now() + timedelta(minutes=2),
                                "window_id": "w1",
                            }
                        ],
                    }
                ]
            ],
            [actor["matched_recordings"] for actor in serialized_actors],
        )

    @snapshot_clickhouse_queries
    def test_wildcard_groups_with_sampling(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "path_groupings": ["between_step_1_*", "between_step_2_*", "step drop*"],
            "sampling_factor": 1,
        }
        path_filter = PathFilter(data=data, team=self.team)
        response = Paths(team=self.team, filter=path_filter).run()
        self.assertCountEqual(
            response,
            [
                {
                    "source": "1_step one",
                    "target": "2_step drop*",
                    "value": 20,
                    "average_conversion_time": 2 * ONE_MINUTE,
                },
                # when we group events for a single user, these effectively become duplicate events, and we choose the last event from
                # a list of duplicate events.
                {
                    "source": "1_step one",
                    "target": "2_between_step_1_*",
                    "value": 15,
                    "average_conversion_time": (5 * 3 + 10 * 2)
                    * ONE_MINUTE
                    / 15,  # first 5 go till between_step_1_c, next 10 go till between_step_1_b
                },
                {
                    "source": "2_between_step_1_*",
                    "target": "3_step two",
                    "value": 15,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "2_step drop*",
                    "target": "3_step branch",
                    "value": 10,
                    "average_conversion_time": ONE_MINUTE,
                },
                {
                    "source": "3_step two",
                    "target": "4_between_step_2_*",
                    "value": 10,
                    "average_conversion_time": 160000,
                },
                {
                    "source": "3_step two",
                    "target": "4_step three",
                    "value": 5,
                    "average_conversion_time": ONE_MINUTE,
                },
            ],
        )


class TestClickhousePathsEdgeValidation(TestCase):
    BASIC_PATH = [("1_a", "2_b"), ("2_b", "3_c"), ("3_c", "4_d")]  # a->b->c->d
    BASIC_PATH_2 = [("1_x", "2_y"), ("2_y", "3_z")]  # x->y->z

    def test_basic_forest(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2

        results = Paths(PathFilter(), MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2)

    def test_basic_forest_with_dangling_edges(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d"), ("2_xxx", "3_yyy")]

        results = Paths(PathFilter(), MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2)

    def test_basic_forest_with_dangling_and_cross_edges(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d"), ("2_y", "3_c")]

        results = Paths(PathFilter(), MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2 + [("2_y", "3_c")])

    def test_no_start_point(self):
        edges = set(self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d")])
        edges.remove(("1_a", "2_b"))  # remove first start point
        edges = list(edges)  # type: ignore

        results = Paths(PathFilter(), MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH_2)
