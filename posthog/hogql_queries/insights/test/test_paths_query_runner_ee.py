import uuid
from datetime import timedelta
from typing import Any
from uuid import UUID

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    create_person_id_override_by_distinct_id,
    snapshot_clickhouse_queries,
)
from unittest.mock import MagicMock, Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from posthog.schema import CachedPathsQueryResponse, PathsLink

from posthog.constants import FUNNEL_PATH_BETWEEN_STEPS, INSIGHT_FUNNELS
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.paths_query_runner import PathsQueryRunner
from posthog.models.group.util import create_group
from posthog.models.instance_setting import override_instance_config
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.test_utils import create_group_type_mapping_without_created_at

ONE_MINUTE = 60_000  # 1 minute in milliseconds


class BaseTestClickhousePaths(ClickhouseTestMixin, APIBaseTest):
    __test__ = False
    maxDiff = None

    def _create_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )

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
        paths_query: dict,
        path_start=None,
        path_end=None,
        funnel_filter=None,
        path_dropoff=None,
    ):
        paths_query = paths_query.copy()
        if "pathsFilter" in paths_query:
            paths_filter = paths_query.pop("pathsFilter")
        else:
            paths_filter = paths_query
            paths_query = {}
        runner = ActorsQueryRunner(
            team=self.team,
            query={
                "select": ["person"],
                "orderBy": ["id"],
                "source": {
                    "kind": "InsightActorsQuery",
                    "source": {
                        "kind": "PathsQuery",
                        **paths_query,
                        "pathsFilter": {
                            **paths_filter,
                            "pathStartKey": path_start,
                            "pathEndKey": path_end,
                            "pathDropoffKey": path_dropoff,
                        },
                    },
                },
            },
        )
        return [row[0]["id"] for row in runner.calculate().model_dump()["results"]]

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
            filter = {"stepLimit": 2}
            result = PathsQueryRunner(query={"kind": "PathsQuery", "pathsFilter": filter}, team=self.team).run()
            assert isinstance(result, CachedPathsQueryResponse)
            response = result.results

            self.assertEqual(
                response,
                [
                    PathsLink(
                        source="1_/1",
                        target="2_/2",
                        value=1,
                        average_conversion_time=ONE_MINUTE,
                    )
                ],
            )
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "1_/1", "2_/2"))
            self.assertEqual([], self._get_people_at_path(filter, "2_/2", "3_/3"))

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = {"stepLimit": 3}
            result = PathsQueryRunner(query={"kind": "PathsQuery", "pathsFilter": filter}, team=self.team).run()
            assert isinstance(result, CachedPathsQueryResponse)
            response = result.results

            self.assertEqual(
                response,
                [
                    PathsLink(
                        source="1_/1",
                        target="2_/2",
                        value=1,
                        average_conversion_time=ONE_MINUTE,
                    ),
                    PathsLink(
                        source="2_/2",
                        target="3_/3",
                        value=1,
                        average_conversion_time=2 * ONE_MINUTE,
                    ),
                ],
            )
            self.assertEqual([p1.uuid], self._get_people_at_path(filter, "2_/2", "3_/3"))

        with freeze_time("2012-01-7T03:21:34.000Z"):
            filter = {"stepLimit": 4}
            result = PathsQueryRunner(query={"kind": "PathsQuery", "pathsFilter": filter}, team=self.team).run()
            assert isinstance(result, CachedPathsQueryResponse)
            response = result.results

            self.assertEqual(
                response,
                [
                    PathsLink(
                        source="1_/1",
                        target="2_/2",
                        value=1,
                        average_conversion_time=ONE_MINUTE,
                    ),
                    PathsLink(
                        source="2_/2",
                        target="3_/3",
                        value=1,
                        average_conversion_time=2 * ONE_MINUTE,
                    ),
                    PathsLink(
                        source="3_/3",
                        target="4_/4",
                        value=1,
                        average_conversion_time=3 * ONE_MINUTE,
                    ),
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

        filter = {"stepLimit": 4, "includeEventTypes": ["$pageview"]}
        result = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": filter,
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=2,
                    average_conversion_time=1.5 * ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=2,
                    average_conversion_time=3 * ONE_MINUTE,
                ),
                PathsLink(
                    source="3_/3",
                    target="4_/4",
                    value=1,
                    average_conversion_time=3 * ONE_MINUTE,
                ),
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

        result = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "dateRange": {
                    "date_from": "2021-05-01",
                    "date_to": "2021-05-03",
                },
                "pathsFilter": {
                    "includeEventTypes": ["custom_event"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_step one",
                    target="2_step two",
                    value=50,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="2_step two",
                    target="3_step three",
                    value=50,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="3_step three",
                    target="4_step branch",
                    value=25,
                    average_conversion_time=60000.0,
                ),
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
        self._create_sample_data_multiple_dropoffs()
        _data = {
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
        funnel_filter: dict = {}
        path_filter: dict = {}
        response: dict = {}
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2021-05-01 00:00:00",
                    "date_to": "2021-05-07 00:00:00",
                },
                "pathsFilter": {
                    "endPoint": "/about",
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/2",
                    target="2_/3",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="1_/3",
                    target="2_/4",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="1_/5",
                    target="2_/about",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="2_/3",
                    target="3_/4",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="2_/4",
                    target="3_/about",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="3_/4",
                    target="4_/5",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="4_/5",
                    target="5_/about",
                    value=1,
                    average_conversion_time=60000.0,
                ),
            ],
        )

        # ensure trailing slashes don't change results
        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2021-05-01 00:00:00",
                    "date_to": "2021-05-07 00:00:00",
                },
                "pathsFilter": {
                    "endPoint": "/about/",
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/2",
                    target="2_/3",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="1_/3",
                    target="2_/4",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="1_/5",
                    target="2_/about",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="2_/3",
                    target="3_/4",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="2_/4",
                    target="3_/about",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="3_/4",
                    target="4_/5",
                    value=1,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="4_/5",
                    target="5_/about",
                    value=1,
                    average_conversion_time=60000.0,
                ),
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 4,
                    "includeEventTypes": ["$pageview"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
            ],
        )

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 4,
                    "includeEventTypes": ["$screen"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/screen1",
                    target="2_/screen2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/screen2",
                    target="3_/screen3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
            ],
        )

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 4,
                    "includeEventTypes": ["custom_event"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/custom1",
                    target="2_/custom2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/custom2",
                    target="3_/custom3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
            ],
        )

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 4,
                    "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                    "excludeEvents": ["/custom1", "/1", "/2", "/3"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/custom2",
                    target="2_/custom3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
                PathsLink(
                    source="1_/screen1",
                    target="2_/screen2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/screen2",
                    target="3_/screen3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 4,
                    "includeEventTypes": ["$pageview"],
                    "excludeEvents": ["/bar/*/foo"],
                    "pathGroupings": ["/bar/*/foo"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/3",
                    value=3,
                    average_conversion_time=3 * ONE_MINUTE,
                )
            ],
        )

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 4,
                    "includeEventTypes": ["$pageview"],
                    "excludeEvents": ["/bar/*/foo"],
                    "pathGroupings": ["/xxx/invalid/*"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

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

        # include everything, exclude nothing
        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {"stepLimit": 10},
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
                PathsLink(
                    source="3_/3",
                    target="4_/screen1",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="4_/screen1",
                    target="5_/screen2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="5_/screen2",
                    target="6_/screen3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
                PathsLink(
                    source="6_/screen3",
                    target="7_/custom1",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="7_/custom1",
                    target="8_/custom2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="8_/custom2",
                    target="9_/custom3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
            ],
        )

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 10,
                    "includeEventTypes": ["$pageview", "$screen"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
                PathsLink(
                    source="3_/3",
                    target="4_/screen1",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="4_/screen1",
                    target="5_/screen2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="5_/screen2",
                    target="6_/screen3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
            ],
        )

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 10,
                    "includeEventTypes": ["$pageview", "custom_event"],
                    "excludeEvents": ["/custom1", "/custom3"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
                PathsLink(
                    source="3_/3",
                    target="4_/custom2",
                    value=1,
                    average_conversion_time=6 * ONE_MINUTE,
                ),
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {},
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=2,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=2,
                    average_conversion_time=3 * ONE_MINUTE,
                ),
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {},
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=2,
                    average_conversion_time=1.5 * ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=2,
                    average_conversion_time=3 * ONE_MINUTE,
                ),
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

        paths_query: dict[str, Any] = {
            "dateRange": {
                "date_from": "2012-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            },
            "pathsFilter": {
                "includeEventTypes": ["$pageview"],
                "startPoint": "/5",
                "endPoint": "/about",
            },
        }
        result = PathsQueryRunner(
            query=paths_query.copy(),
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/5",
                    target="2_/about",
                    value=2,
                    average_conversion_time=60000.0,
                )
            ],
        )
        self.assertCountEqual(self._get_people_at_path(paths_query.copy(), "1_/5", "2_/about"), [p1.uuid, p2.uuid])

        # test aggregation for long paths
        paths_query["pathsFilter"]["startPoint"] = "/2"
        paths_query["pathsFilter"]["stepLimit"] = 4
        result = PathsQueryRunner(
            query=paths_query,
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/2",
                    target="2_/3",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/3",
                    target="3_...",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="3_...",
                    target="4_/5",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="4_/5",
                    target="5_/about",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
            ],
        )
        self.assertCountEqual(self._get_people_at_path(paths_query, "3_...", "4_/5"), [p1.uuid])

    @snapshot_clickhouse_queries
    def test_properties_queried_using_path_filter(self):
        test_cases = {
            "empty_filter": ({}, (True, True)),
            "include_pageview": ({"includeEventTypes": ["$pageview"]}, (True, False)),
            "include_screen": ({"includeEventTypes": ["$screen"]}, (False, True)),
            "include_custom_events": (
                {
                    "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                },
                (True, True),
            ),
            "exclude_custom1": (
                {
                    "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                    "excludeEvents": ["/custom1"],
                },
                (True, True),
            ),
            "exclude_pageview": (
                {
                    "excludeEvents": ["$pageview"],
                },
                (False, True),
            ),
        }

        for test_name, (filter, expected) in test_cases.items():
            with self.subTest(test_name):
                q = {
                    "kind": "PathsQuery",
                    "pathsFilter": filter,
                }
                path_query_runner = PathsQueryRunner(query=q, team=self.team)
                result = (
                    path_query_runner._should_query_event("$pageview"),
                    path_query_runner._should_query_event("$screen"),
                )
                self.assertEqual(result, expected)

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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "stepLimit": 4,
                    "includeEventTypes": ["$pageview"],
                    "pathGroupings": ["/bar/*/foo"],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/bar/*/foo",
                    value=3,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/bar/*/foo",
                    target="3_/3",
                    value=3,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                },
                "pathsFilter": {
                    "includeEventTypes": ["$pageview"],
                    "pathGroupings": [
                        "(a+)+",
                        "[aaa|aaaa]+",
                        "1.*",
                        ".*",
                        "/3?q=1",
                        "/3*",
                    ],
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/3*",
                    value=1,
                    average_conversion_time=3 * ONE_MINUTE,
                ),
                PathsLink(
                    source=f"1_{evil_string}",
                    target="2_/2/bar/aaa",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2/bar/aaa",
                    target="3_/3*",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
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

        filter = {
            "pathsFilter": {
                "includeEventTypes": ["custom_event"],
            },
            "dateRange": {
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
            },
        }
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2021-05-01 00:00:00",
                    "date_to": "2021-05-07 00:00:00",
                },
                "pathsFilter": {
                    "startPoint": "/2",
                    "edgeLimit": 6,
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/2",
                    target="2_/3",
                    value=5,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="2_/3",
                    target="3_/4",
                    value=5,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="3_/4",
                    target="4_/5",
                    value=5,
                    average_conversion_time=60000.0,
                ),
                PathsLink(
                    source="4_/5",
                    target="5_/about",
                    value=5,
                    average_conversion_time=60000.0,
                ),
                # PathsLink(source='3_/x', target='4_/about', value=2, average_conversion_time=60000.0), # gets deleted by validation since dangling
                PathsLink(
                    source="1_/2",
                    target="2_/a",
                    value=1,
                    average_conversion_time=30000.0,
                ),
            ],
        )

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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                    "date_to": "2012-02-01",
                },
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "group_type_index": 0,
                                    "key": "industry",
                                    "operator": "exact",
                                    "type": "group",
                                    "value": ["finance"],
                                }
                            ],
                        }
                    ],
                },
                "pathsFilter": {
                    "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                    "stepLimit": 4,
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
            ],
        )

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                    "date_to": "2012-02-01",
                },
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "group_type_index": 0,
                                    "key": "industry",
                                    "operator": "exact",
                                    "type": "group",
                                    "value": ["technology"],
                                }
                            ],
                        }
                    ],
                },
                "pathsFilter": {
                    "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                    "stepLimit": 4,
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/screen1",
                    target="2_/screen2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/screen2",
                    target="3_/screen3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
            ],
        )

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                    "date_to": "2012-02-01",
                },
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "group_type_index": 1,
                                    "key": "industry",
                                    "operator": "exact",
                                    "type": "group",
                                    "value": ["technology"],
                                }
                            ],
                        }
                    ],
                },
                "pathsFilter": {
                    "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                    "stepLimit": 4,
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/custom1",
                    target="2_/custom2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/custom2",
                    target="3_/custom3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                    "date_to": "2012-02-01",
                },
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "group_type_index": 0,
                                    "key": "industry",
                                    "operator": "exact",
                                    "type": "group",
                                    "value": ["finance"],
                                }
                            ],
                        }
                    ],
                },
                "pathsFilter": {
                    "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                    "stepLimit": 4,
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            self.assertEqual(
                response,
                [
                    PathsLink(
                        source="1_/1",
                        target="2_/2",
                        value=1,
                        average_conversion_time=ONE_MINUTE,
                    ),
                    PathsLink(
                        source="2_/2",
                        target="3_/3",
                        value=1,
                        average_conversion_time=2 * ONE_MINUTE,
                    ),
                ],
            )

            result = PathsQueryRunner(
                query={
                    "dateRange": {
                        "date_from": "2012-01-01",
                        "date_to": "2012-02-01",
                    },
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "group_type_index": 0,
                                        "key": "industry",
                                        "operator": "exact",
                                        "type": "group",
                                        "value": ["technology"],
                                    }
                                ],
                            }
                        ],
                    },
                    "pathsFilter": {
                        "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                        "stepLimit": 4,
                    },
                },
                team=self.team,
            ).run()
            assert isinstance(result, CachedPathsQueryResponse)
            response = result.results

            self.assertEqual(
                response,
                [
                    PathsLink(
                        source="1_/screen1",
                        target="2_/screen2",
                        value=1,
                        average_conversion_time=ONE_MINUTE,
                    ),
                    PathsLink(
                        source="2_/screen2",
                        target="3_/screen3",
                        value=1,
                        average_conversion_time=2 * ONE_MINUTE,
                    ),
                ],
            )

            result = PathsQueryRunner(
                query={
                    "dateRange": {
                        "date_from": "2012-01-01",
                        "date_to": "2012-02-01",
                    },
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "group_type_index": 1,
                                        "key": "industry",
                                        "operator": "exact",
                                        "type": "group",
                                        "value": ["technology"],
                                    }
                                ],
                            }
                        ],
                    },
                    "pathsFilter": {
                        "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                        "stepLimit": 4,
                    },
                },
                team=self.team,
            ).run()
            assert isinstance(result, CachedPathsQueryResponse)
            response = result.results

            self.assertEqual(
                response,
                [
                    PathsLink(
                        source="1_/custom1",
                        target="2_/custom2",
                        value=1,
                        average_conversion_time=ONE_MINUTE,
                    ),
                    PathsLink(
                        source="2_/custom2",
                        target="3_/custom3",
                        value=1,
                        average_conversion_time=2 * ONE_MINUTE,
                    ),
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

        result = PathsQueryRunner(
            query={
                "dateRange": {
                    "date_from": "2012-01-01",
                    "date_to": "2012-02-01",
                },
                "pathsFilter": {
                    "includeEventTypes": ["$pageview", "$screen", "custom_event"],
                    "stepLimit": 4,
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(
            response,
            [
                PathsLink(
                    source="1_/1",
                    target="2_/2",
                    value=1,
                    average_conversion_time=ONE_MINUTE,
                ),
                PathsLink(
                    source="2_/2",
                    target="3_/3",
                    value=1,
                    average_conversion_time=2 * ONE_MINUTE,
                ),
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

        results = (
            ActorsQueryRunner(
                query={
                    "orderBy": ["id"],
                    "select": ["person", "created_at", "event_count", "matched_recordings"],
                    "source": {
                        "kind": "InsightActorsQuery",
                        "source": {
                            "dateRange": {
                                "date_from": "2012-01-01 00:00:00",
                                "date_to": "2012-01-02 00:00:00",
                            },
                            "kind": "PathsQuery",
                            "pathsFilter": {
                                "includeEventTypes": ["$pageview"],
                                "pathEndKey": "2_/2",
                            },
                        },
                    },
                },
                team=self.team,
            )
            .calculate()
            .model_dump()["results"]
        )

        self.assertCountEqual([p1.uuid, p2.uuid], [row[0]["id"] for row in results])
        matched_recordings = [list(row[3]) for row in results]

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

        results = (
            ActorsQueryRunner(
                query={
                    "orderBy": ["id"],
                    "select": ["person", "created_at", "event_count", "matched_recordings"],
                    "source": {
                        "kind": "InsightActorsQuery",
                        "source": {
                            "dateRange": {
                                "date_from": "2012-01-01 00:00:00",
                                "date_to": "2012-01-02 00:00:00",
                            },
                            "kind": "PathsQuery",
                            "pathsFilter": {
                                "includeEventTypes": ["$pageview"],
                                "pathEndKey": "2_/2",
                            },
                        },
                    },
                },
                team=self.team,
            )
            .calculate()
            .model_dump()["results"]
        )

        self.assertEqual([p1.uuid], [row[0]["id"] for row in results])
        self.assertEqual([[]], [list(row[3]) for row in results])

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

        results = (
            ActorsQueryRunner(
                query={
                    "orderBy": ["id"],
                    "select": ["person", "created_at", "event_count", "matched_recordings"],
                    "source": {
                        "kind": "InsightActorsQuery",
                        "source": {
                            "dateRange": {
                                "date_from": "2012-01-01 00:00:00",
                                "date_to": "2012-01-02 00:00:00",
                            },
                            "kind": "PathsQuery",
                            "pathsFilter": {
                                "includeEventTypes": ["$pageview"],
                                "startPoint": "/1",
                                "endPoint": "/3",
                                "pathEndKey": "2_/2",
                            },
                        },
                    },
                },
                team=self.team,
            )
            .calculate()
            .model_dump()["results"]
        )

        self.assertEqual([p1.uuid], [row[0]["id"] for row in results])
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
            [list(row[3]) for row in results],
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
        results = (
            ActorsQueryRunner(
                query={
                    "orderBy": ["id"],
                    "select": ["person", "created_at", "event_count", "matched_recordings"],
                    "source": {
                        "kind": "InsightActorsQuery",
                        "source": {
                            "dateRange": {
                                "date_from": "2012-01-01 00:00:00",
                                "date_to": "2012-01-02 00:00:00",
                            },
                            "kind": "PathsQuery",
                            "pathsFilter": {
                                "includeEventTypes": ["$pageview"],
                                "pathDropoffKey": "2_/2",
                            },
                        },
                    },
                },
                team=self.team,
            )
            .calculate()
            .model_dump()["results"]
        )

        self.assertEqual([], results)

        # Matching events for dropoff
        results = (
            ActorsQueryRunner(
                query={
                    "orderBy": ["id"],
                    "select": ["person", "created_at", "event_count", "matched_recordings"],
                    "source": {
                        "kind": "InsightActorsQuery",
                        "source": {
                            "dateRange": {
                                "date_from": "2012-01-01 00:00:00",
                                "date_to": "2012-01-02 00:00:00",
                            },
                            "kind": "PathsQuery",
                            "pathsFilter": {
                                "includeEventTypes": ["$pageview"],
                                "pathDropoffKey": "3_/3",
                            },
                        },
                    },
                },
                team=self.team,
            )
            .calculate()
            .model_dump()["results"]
        )

        self.assertEqual([p1.uuid], [row[0]["id"] for row in results])
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
            [list(row[3]) for row in results],
        )


insight_funnels_use_udf_funnel_flag_side_effect = lambda key, *args, **kwargs: key == "insight-funnels-use-udf"


class ClickhousePathsUDF(BaseTestClickhousePaths):
    __test__ = True


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=insight_funnels_use_udf_funnel_flag_side_effect))
class TestClickhousePathsUDF(BaseTestClickhousePaths):
    __test__ = True


class TestClickhousePathsEdgeValidation(TestCase):
    BASIC_PATH = [("1_a", "2_b"), ("2_b", "3_c"), ("3_c", "4_d")]  # a->b->c->d
    BASIC_PATH_2 = [("1_x", "2_y"), ("2_y", "3_z")]  # x->y->z

    def test_basic_forest(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2

        results = PathsQueryRunner(query={"pathsFilter": {}}, team=MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2)

    def test_basic_forest_with_dangling_edges(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d"), ("2_xxx", "3_yyy")]

        results = PathsQueryRunner(query={"pathsFilter": {}}, team=MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2)

    def test_basic_forest_with_dangling_and_cross_edges(self):
        edges = self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d"), ("2_y", "3_c")]

        results = PathsQueryRunner(query={"pathsFilter": {}}, team=MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH + self.BASIC_PATH_2 + [("2_y", "3_c")])

    def test_no_start_point(self):
        edges = set(self.BASIC_PATH + self.BASIC_PATH_2 + [("2_w", "3_z"), ("3_x", "4_d")])
        edges.remove(("1_a", "2_b"))  # remove first start point
        edges = list(edges)  # type: ignore

        results = PathsQueryRunner(query={"pathsFilter": {}}, team=MagicMock()).validate_results(edges)

        self.assertCountEqual(results, self.BASIC_PATH_2)
