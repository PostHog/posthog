from typing import Optional
from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime

from zoneinfo import ZoneInfo

from django.test import override_settings
from freezegun import freeze_time

from posthog.clickhouse.client.execute import sync_execute
from posthog.constants import (
    RETENTION_FIRST_TIME,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models import Action
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person
from posthog.schema import RetentionQuery
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    snapshot_clickhouse_queries,
)

from posthog.hogql_queries.insights.trends.breakdown import BREAKDOWN_OTHER_STRING_LABEL


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name}])
    return action


def _create_signup_actions(team, user_and_timestamps):
    for distinct_id, timestamp in user_and_timestamps:
        _create_event(team=team, event="sign up", distinct_id=distinct_id, timestamp=timestamp)
    sign_up_action = _create_action(team=team, name="sign up")
    return sign_up_action


def _date(day, hour=5, month=0, minute=0):
    return datetime(2020, 6 + month, 10 + day, hour, minute).isoformat()


def pluck(list_of_dicts, key, child_key=None):
    return [pluck(d[key], child_key) if child_key else d[key] for d in list_of_dicts]


def pad(retention_result: list[list[int]]) -> list[list[int]]:
    """
    changes the old 'triangle' format to the new 'matrix' format
    after retention updates
    """
    result = []
    max_length = max(len(row) for row in retention_result)

    for row in retention_result:
        if len(row) < max_length:
            row.extend([0] * (max_length - len(row)))

        result.append(row)

    return result


def _create_events(team, user_and_timestamps, event="$pageview"):
    i = 0
    for distinct_id, timestamp, *properties_args in user_and_timestamps:
        properties = {"$some_property": "value"} if i % 2 == 0 else {}
        if len(properties_args) == 1:
            properties.update(properties_args[0])

        _create_event(
            team=team,
            event=event,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
        )
        i += 1


class TestRetention(ClickhouseTestMixin, APIBaseTest):
    def run_query(self, query):
        if not query.get("retentionFilter"):
            query["retentionFilter"] = {}
        runner = RetentionQueryRunner(team=self.team, query=query)
        return runner.calculate().model_dump()["results"]

    def run_actors_query(self, interval, query, select=None, search=None, breakdown=None):
        query["kind"] = "RetentionQuery"
        if not query.get("retentionFilter"):
            query["retentionFilter"] = {}
        runner = ActorsQueryRunner(
            team=self.team,
            query={
                "search": search,
                "select": ["person", "appearances", *(select or [])],
                "orderBy": ["length(appearances) DESC", "actor_id"],
                "source": {
                    "kind": "InsightActorsQuery",
                    "interval": interval,
                    "source": query,
                    "breakdown": breakdown,
                },
            },
        )
        return runner.calculate().model_dump()["results"]

    def test_retention_default(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "retentionFilter": {
                    "totalIntervals": 11,
                }
            }
        )
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_day_interval(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        # even if set to hour 6 it should default to beginning of day and include all pageviews above
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            }
        )
        self.assertEqual(len(result), 11)
        self.assertEqual(
            pluck(result, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0],
                    [2, 2, 1, 0, 1, 2, 0, 0, 0, 0],
                    [2, 1, 0, 1, 2, 0, 0, 0, 0],
                    [1, 0, 0, 1, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_month_interval(self):
        _create_person(
            team=self.team,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        _create_events(
            self.team,
            [
                ("person1", _date(day=0, month=-5)),
                ("person2", _date(day=0, month=-5)),
                ("person1", _date(day=0, month=-4)),
                ("person2", _date(day=0, month=-4)),
                ("person1", _date(day=0, month=-3)),
                ("person2", _date(day=0, month=-3)),
                ("person1", _date(day=0, month=-1)),
                ("person1", _date(day=0, month=0)),
                ("person2", _date(day=0, month=0)),
                ("person2", _date(day=0, month=1)),
                ("person1", _date(day=0, month=3)),
                ("person2", _date(day=0, month=5)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(15, month=5, hour=0)},
                "retentionFilter": {
                    "period": "Month",
                    "totalIntervals": 11,
                },
            }
        )

        self.assertEqual(
            pluck(result, "label"),
            [
                "Month 0",
                "Month 1",
                "Month 2",
                "Month 3",
                "Month 4",
                "Month 5",
                "Month 6",
                "Month 7",
                "Month 8",
                "Month 9",
                "Month 10",
            ],
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 2, 2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [2, 2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 0, 0, 1, 0, 0],
                    [2, 1, 0, 1, 0, 1],
                    [1, 0, 0, 0, 1],
                    [0, 0, 0, 0],
                    [1, 0, 0],
                    [0, 0],
                    [1],
                ]
            ),
        )

        self.assertEqual(
            pluck(result, "date"),
            [
                datetime(2020, 1, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 2, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 3, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 4, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 5, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 8, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 9, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 10, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 11, 1, 0, tzinfo=ZoneInfo("UTC")),
            ],
        )

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
    @snapshot_clickhouse_queries
    def test_month_interval_with_person_on_events_v2(self):
        _create_person(
            team=self.team,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        person_id1 = str(uuid.uuid4())
        person_id2 = str(uuid.uuid4())
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person1",
            person_id=person_id1,
            timestamp=_date(day=0, month=-5),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person2",
            person_id=person_id2,
            timestamp=_date(day=0, month=-4),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person1",
            person_id=person_id1,
            timestamp=_date(day=0, month=-3),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person2",
            person_id=person_id2,
            timestamp=_date(day=0, month=-2),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person1",
            person_id=person_id1,
            timestamp=_date(day=0, month=-1),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person2",
            person_id=person_id2,
            timestamp=_date(day=0, month=0),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person1",
            person_id=person_id1,
            timestamp=_date(day=0, month=1),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person2",
            person_id=person_id2,
            timestamp=_date(day=0, month=2),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person1",
            person_id=person_id1,
            timestamp=_date(day=0, month=3),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person2",
            person_id=person_id2,
            timestamp=_date(day=0, month=4),
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="person1",
            person_id=person_id1,
            timestamp=_date(day=0, month=5),
        )

        _create_events(
            self.team,
            [
                ("person1", _date(day=0, month=-5)),
                ("person2", _date(day=0, month=-4)),
                ("person1", _date(day=0, month=-3)),
                ("person2", _date(day=0, month=-2)),
                ("person1", _date(day=0, month=-1)),
                ("person2", _date(day=0, month=0)),
                ("person1", _date(day=0, month=1)),
                ("person2", _date(day=0, month=2)),
                ("person1", _date(day=0, month=3)),
                ("person2", _date(day=0, month=4)),
                ("person1", _date(day=0, month=5)),
            ],
        )

        create_person_id_override_by_distinct_id("person1", "person2", self.team.pk)

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(0, month=5, hour=0)},
                "retentionFilter": {
                    "period": "Month",
                    "totalIntervals": 11,
                },
            }
        )

        self.assertEqual(
            pluck(result, "label"),
            [
                "Month 0",
                "Month 1",
                "Month 2",
                "Month 3",
                "Month 4",
                "Month 5",
                "Month 6",
                "Month 7",
                "Month 8",
                "Month 9",
                "Month 10",
            ],
        )

        # We expect 1s across the board due to the override set up from person1 to person2, making them the same person
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1],
                    [1, 1, 1, 1],
                    [1, 1, 1],
                    [1, 1],
                    [1],
                ]
            ),
        )

        self.assertEqual(
            pluck(result, "date"),
            [
                datetime(2020, 1, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 2, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 3, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 4, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 5, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 8, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 9, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 10, 1, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 11, 1, 0, tzinfo=ZoneInfo("UTC")),
            ],
        )

    @snapshot_clickhouse_queries
    def test_week_interval(self):
        _create_person(
            team=self.team,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person2", _date(0)),
                ("person1", _date(1)),
                ("person2", _date(1)),
                ("person1", _date(7)),
                ("person2", _date(7)),
                ("person1", _date(14)),
                ("person1", _date(month=1, day=-6)),
                ("person2", _date(month=1, day=-6)),
                ("person2", _date(month=1, day=1)),
                ("person1", _date(month=1, day=1)),
                ("person2", _date(month=1, day=15)),
            ],
        )

        # Starting with Sunday
        query = {
            "dateRange": {"date_to": _date(10, month=1, hour=0)},
            "retentionFilter": {
                "period": "Week",
                "totalIntervals": 7,
            },
        }
        result_sunday = self.run_query(query=query)

        self.assertEqual(
            pluck(result_sunday, "label"),
            ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
        )

        self.assertEqual(
            pluck(result_sunday, "values", "count"),
            pad(
                [
                    [2, 2, 1, 2, 2, 0, 1],
                    [2, 1, 2, 2, 0, 1],
                    [1, 1, 1, 0, 0],
                    [2, 2, 0, 1],
                    [2, 0, 1],
                    [0, 0],
                    [1],
                ]
            ),
        )

        self.assertEqual(
            pluck(result_sunday, "date"),
            [
                datetime(2020, 6, 7, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 14, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 21, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 28, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 5, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 12, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 19, 0, tzinfo=ZoneInfo("UTC")),
            ],
        )

        # Starting with Monday
        self.team.week_start_day = 1  # WeekStartDay.MONDAY's concrete value
        self.team.save()

        result_monday = self.run_query(query=query)

        self.assertEqual(
            pluck(result_monday, "label"),
            ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
        )

        self.assertEqual(
            pluck(result_monday, "values", "count"),
            pad(
                [
                    [2, 2, 1, 2, 2, 0, 1],
                    [2, 1, 2, 2, 0, 1],
                    [1, 1, 1, 0, 0],
                    [2, 2, 0, 1],
                    [2, 0, 1],
                    [0, 0],
                    [1],
                ]
            ),
        )

        self.assertEqual(
            pluck(result_monday, "date"),
            [
                datetime(2020, 6, 8, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 15, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 22, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 29, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 6, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 13, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 20, 0, tzinfo=ZoneInfo("UTC")),
            ],
        )

    def test_hour_interval(self):
        _create_person(
            team=self.team,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        _create_events(
            self.team,
            [
                ("person1", _date(day=0, hour=6)),
                ("person2", _date(day=0, hour=6)),
                ("person1", _date(day=0, hour=7)),
                ("person2", _date(day=0, hour=7)),
                ("person1", _date(day=0, hour=8)),
                ("person2", _date(day=0, hour=8)),
                ("person1", _date(day=0, hour=10)),
                ("person1", _date(day=0, hour=11)),
                ("person2", _date(day=0, hour=11)),
                ("person2", _date(day=0, hour=12)),
                ("person1", _date(day=0, hour=14)),
                ("person2", _date(day=0, hour=16)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(0, hour=16, minute=13)},
                "retentionFilter": {
                    "period": "Hour",
                    "totalIntervals": 11,
                },
            }
        )

        self.assertEqual(
            pluck(result, "label"),
            [
                "Hour 0",
                "Hour 1",
                "Hour 2",
                "Hour 3",
                "Hour 4",
                "Hour 5",
                "Hour 6",
                "Hour 7",
                "Hour 8",
                "Hour 9",
                "Hour 10",
            ],
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 2, 2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [2, 2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 0, 0, 1, 0, 0],
                    [2, 1, 0, 1, 0, 1],
                    [1, 0, 0, 0, 1],
                    [0, 0, 0, 0],
                    [1, 0, 0],
                    [0, 0],
                    [1],
                ]
            ),
        )

        self.assertEqual(
            pluck(result, "date"),
            [
                datetime(2020, 6, 10, 6, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 7, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 8, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 9, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 10, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 11, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 12, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 13, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 14, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 15, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 10, 16, tzinfo=ZoneInfo("UTC")),
            ],
        )

    def test_hour_interval_team_timezone(self):
        self.team.timezone = "US/Pacific"
        self.team.save()

        _create_person(
            team=self.team,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        _create_events(
            self.team,
            [
                ("person1", _date(day=0, hour=6)),
                ("person2", _date(day=0, hour=6)),
                ("person1", _date(day=0, hour=7)),
                ("person2", _date(day=0, hour=7)),
                ("person1", _date(day=0, hour=8)),
                ("person2", _date(day=0, hour=8)),
                ("person1", _date(day=0, hour=10)),
                ("person1", _date(day=0, hour=11)),
                ("person2", _date(day=0, hour=11)),
                ("person2", _date(day=0, hour=12)),
                ("person1", _date(day=0, hour=14)),
                ("person2", _date(day=0, hour=16)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(0, hour=16, minute=13)},
                "retentionFilter": {
                    "period": "Hour",
                    "totalIntervals": 11,
                },
            }
        )

        self.assertEqual(
            pluck(result, "label"),
            [
                "Hour 0",
                "Hour 1",
                "Hour 2",
                "Hour 3",
                "Hour 4",
                "Hour 5",
                "Hour 6",
                "Hour 7",
                "Hour 8",
                "Hour 9",
                "Hour 10",
            ],
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 2, 2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [2, 2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [2, 0, 1, 2, 1, 0, 1, 0, 1],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 0, 0, 1, 0, 0],
                    [2, 1, 0, 1, 0, 1],
                    [1, 0, 0, 0, 1],
                    [0, 0, 0, 0],
                    [1, 0, 0],
                    [0, 0],
                    [1],
                ]
            ),
        )

        self.assertEqual(
            pluck(result, "date"),
            [
                datetime(2020, 6, 10, 6, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 7, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 8, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 9, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 10, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 11, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 12, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 13, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 14, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 15, tzinfo=ZoneInfo("US/Pacific")),
                datetime(2020, 6, 10, 16, tzinfo=ZoneInfo("US/Pacific")),
            ],
        )

    # ensure that the first interval is properly rounded according to the specified period
    def test_interval_rounding(self):
        _create_person(
            team=self.team,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person2", _date(0)),
                ("person1", _date(1)),
                ("person2", _date(1)),
                ("person1", _date(7)),
                ("person2", _date(7)),
                ("person1", _date(14)),
                ("person1", _date(month=1, day=-6)),
                ("person2", _date(month=1, day=-6)),
                ("person2", _date(month=1, day=1)),
                ("person1", _date(month=1, day=1)),
                ("person2", _date(month=1, day=15)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(14, month=1, hour=0)},
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                },
            }
        )

        self.assertEqual(
            pluck(result, "label"),
            ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad([[2, 2, 1, 2, 2, 0, 1], [2, 1, 2, 2, 0, 1], [1, 1, 1, 0, 0], [2, 2, 0, 1], [2, 0, 1], [0, 0], [1]]),
        )

        self.assertEqual(
            pluck(result, "date"),
            [
                datetime(2020, 6, 7, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 14, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 21, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 6, 28, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 5, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 12, 0, tzinfo=ZoneInfo("UTC")),
                datetime(2020, 7, 19, 0, tzinfo=ZoneInfo("UTC")),
            ],
        )

    def test_rolling_retention(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])
        _create_person(team_id=self.team.pk, distinct_ids=["person5"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(3)),
                ("person1", _date(4)),
                ("person2", _date(0)),
                ("person2", _date(1)),
                ("person3", _date(1)),
                ("person3", _date(2)),
                ("person3", _date(3)),
                ("person4", _date(3)),
                ("person4", _date(4)),
                ("person5", _date(4)),
            ],
        )

        result = self.run_query(
            query={
                # _date(0) is ignored
                # day 0 is _date(1)
                "dateRange": {"date_to": _date(5, hour=6)},
                "retentionFilter": {
                    "cumulative": True,
                    "totalIntervals": 5,
                    "targetEntity": {"id": None, "name": "All events"},
                    "returningEntity": {"id": None, "name": "All events"},
                },
            }
        )
        self.assertEqual(
            pluck(result, "values", "count"),
            pad([[2, 1, 1, 0, 0], [1, 1, 0, 0], [3, 2, 0], [3, 0], [0]]),
        )

    def test_rolling_retention_with_minimum_occurrences(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])
        _create_person(team_id=self.team.pk, distinct_ids=["person5"])
        minimum_occurrences = 3

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(3)),
                *[("person1", _date(4))] * minimum_occurrences,
                ("person2", _date(0)),
                ("person2", _date(1)),
                ("person3", _date(1)),
                ("person3", _date(2)),
                *[("person3", _date(3))] * minimum_occurrences,
                ("person4", _date(3)),
                ("person4", _date(4)),
                ("person5", _date(4)),
            ],
        )

        result = self.run_query(
            query={
                # _date(0) is ignored
                # day 0 is _date(1)
                "dateRange": {"date_to": _date(5, hour=6)},
                "retentionFilter": {
                    "cumulative": True,
                    "totalIntervals": 5,
                    "minimumOccurrences": minimum_occurrences,
                    "targetEntity": {"id": None, "name": "All events"},
                    "returningEntity": {"id": None, "name": "All events"},
                },
            }
        )
        self.assertEqual(
            pad([[2, 1, 1, 0, 0], [1, 1, 0, 0], [3, 1, 0], [3, 0], [0]]),
            pluck(result, "values", "count"),
        )

    def test_rolling_retention_doesnt_double_count_same_user(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])
        _create_person(team_id=self.team.pk, distinct_ids=["person5"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(3)),
                ("person1", _date(4)),
                ("person2", _date(0)),
                ("person2", _date(1)),
                ("person3", _date(1)),
                ("person3", _date(2)),
                ("person3", _date(3)),
                ("person4", _date(3)),
                ("person4", _date(4)),
                ("person5", _date(4)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=6)},
                "retentionFilter": {
                    "cumulative": True,
                    "totalIntervals": 6,
                    "targetEntity": {"id": None, "name": "All events"},
                    "returningEntity": {"id": None, "name": "All events"},
                },
            }
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    # first row, [2, 2, 1, 1, 0, 0], is explained below
                    # day 0 is person 1, 2 -> 2
                    # day 1 is person 2, 3 -> 1 (but we see person 1 later) so becomes 2
                    # day 2 is person 3 -> 0 (but we see person 1 later) so becomes 1
                    # day 3 is person 1, 3, 4 -> 1 (won't double count person 1 even though we see them again later)
                    # day 4 is person 1, 4, 5 -> 1
                    # day 5 is no one -> 0
                    [2, 2, 1, 1, 1, 0],
                    [2, 1, 1, 0, 0],
                    [1, 1, 0, 0],
                    [3, 2, 0],
                    [3, 0],
                    [0],
                ]
            ),
        )

    def test_all_events(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                    "targetEntity": {"id": None, "name": "All events"},
                    "returningEntity": {"id": "$pageview", "type": "events"},
                },
            }
        )
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0],
                    [2, 2, 1, 0, 1, 2, 0, 0, 0, 0],
                    [2, 1, 0, 1, 2, 0, 0, 0, 0],
                    [1, 0, 0, 1, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {
                    "event": None,
                },
                {"event": "non_matching_event"},
            ],
        )
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                    "targetEntity": {"id": action.id, "type": TREND_FILTER_TYPE_ACTIONS},
                    "returningEntity": {"id": "$pageview", "type": "events"},
                },
            }
        )
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0],
                    [2, 2, 1, 0, 1, 2, 0, 0, 0, 0],
                    [2, 1, 0, 1, 2, 0, 0, 0, 0],
                    [1, 0, 0, 1, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_all_events_with_minimum_occurrences(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                    "targetEntity": {"id": None, "name": "All events"},
                    "returningEntity": {"id": "$pageview", "type": "events"},
                    "minimumOccurrences": 2,
                },
            }
        )
        self.assertEqual(
            pad(
                [
                    [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
                    [2, 0, 0, 0, 1, 0, 0, 0, 0, 0],
                    [2, 0, 0, 1, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
            pluck(result, "values", "count"),
        )

    def test_all_events_target_first_time(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
            ],
            "event1",
        )

        _create_events(
            self.team,
            [
                ("person1", _date(2)),
                ("person1", _date(3)),
            ],
            "event2",
        )

        result_all_events = self.run_query(
            query={
                "dateRange": {"date_to": _date(2, hour=6)},
                "retentionFilter": {
                    "retentionType": "retention_first_time",
                    "totalIntervals": 4,
                    "targetEntity": {"id": "event2", "type": "events"},
                    "returningEntity": {"id": None, "name": "All events"},
                },
            }
        )

        result_specific_event = self.run_query(
            query={
                "dateRange": {"date_to": _date(2, hour=6)},
                "retentionFilter": {
                    "retentionType": "retention_first_time",
                    "totalIntervals": 4,
                    "targetEntity": {"id": "event2", "type": "events"},
                    "returningEntity": {"id": "event2", "type": "events"},
                },
            }
        )

        self.assertEqual(
            pluck(result_specific_event, "values", "count"),
            pad(
                [
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [1],
                ]
            ),
        )

        self.assertEqual(result_specific_event, result_all_events)

    def test_retention_people_basic(self):
        person1 = _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        # even if set to hour 6 it should default to beginning of day and include all pageviews above
        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            },
        )
        self.assertEqual(len(result), 1, result)
        self.assertEqual(result[0][0]["id"], person1.uuid, person1.uuid)

        # test selecting appearances directly (defauly: days)
        result_2 = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            },
            select=["day_0", "day_1", "day_2", "day_3", "day_4"],
        )
        self.assertEqual(len(result_2), len(result))
        self.assertEqual(result_2[0][2], 1)  # day_0
        self.assertEqual(result_2[0][3], 1)  # day_1
        self.assertEqual(result_2[0][4], 1)  # day_2
        self.assertEqual(result_2[0][5], 0)  # day_3
        self.assertEqual(result_2[0][6], 0)  # day_4

    def test_retention_people_first_time(self):
        _, _, p3, _ = self._create_first_time_retention_events()
        # even if set to hour 6 it should default to beginning of day and include all pageviews above

        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "targetEntity": {"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS},
                    "returningEntity": {"id": "$pageview", "type": "events"},
                    "retentionType": RETENTION_FIRST_TIME,
                    "totalIntervals": 11,
                },
            },
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0]["id"], p3.uuid)

        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(14, hour=6)},
                "retentionFilter": {
                    "targetEntity": {"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS},
                    "returningEntity": {"id": "$pageview", "type": "events"},
                    "retentionType": RETENTION_FIRST_TIME,
                },
            },
        )

        self.assertEqual(len(result), 0)

    def test_retention_people_in_period(self):
        person1 = _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        person2 = _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
                ("person2", _date(7)),
            ],
        )

        # even if set to hour 6 it should default to beginning of day and include all pageviews above
        result = self.run_actors_query(
            interval=2,
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            },
        )

        # should be descending order on number of appearances
        self.assertEqual(result[0][0]["id"], person2.uuid)
        self.assertCountEqual(result[0][1], [0, 1, 4, 5])

        self.assertEqual(result[1][0]["id"], person1.uuid)
        self.assertCountEqual(result[1][1], [0, 3, 4])

    def test_retention_people_search(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
                ("person2", _date(7)),
            ],
        )

        result = self.run_actors_query(
            interval=2,
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            },
            search="test",
        )
        self.assertEqual(len(result), 2)

    def test_retention_people_in_period_first_time(self):
        p1, p2, p3, p4 = self._create_first_time_retention_events()
        # even if set to hour 6 it should default to beginning of day and include all pageviews above
        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "targetEntity": {"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS},
                    "returningEntity": {"id": "$pageview", "type": "events"},
                    "retentionType": RETENTION_FIRST_TIME,
                    "totalIntervals": 11,
                },
            },
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0]["id"], p3.uuid)
        self.assertCountEqual(result[0][1], [0, 1, 3, 4, 5])

    def test_retention_multiple_events(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        first_event = "$some_event"
        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(3)),
                ("person2", _date(0)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person3", _date(5)),
            ],
            first_event,
        )

        _create_events(
            self.team,
            [("person1", _date(5)), ("person1", _date(6)), ("person2", _date(5))],
            "$pageview",
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(6, hour=6)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "targetEntity": {"id": first_event, "name": first_event, "type": TREND_FILTER_TYPE_EVENTS},
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
            }
        )
        self.assertEqual(len(result), 7)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 0, 0, 0, 0, 2, 1],
                    [2, 0, 0, 0, 2, 1],
                    [2, 0, 0, 2, 1],
                    [2, 0, 2, 1],
                    [0, 0, 0],
                    [1, 0],
                    [0],
                ]
            ),
        )

    def test_retention_any_event(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(3)),
                ("person2", _date(0)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person3", _date(5)),
            ],
            "$some_event",
        )

        _create_events(
            self.team,
            [("person1", _date(5)), ("person1", _date(6)), ("person2", _date(5))],
            "$pageview",
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(6, hour=6)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "targetEntity": {"id": None, "type": "events"},
                    "returningEntity": {"id": None, "type": "events"},
                },
            }
        )
        self.assertEqual(len(result), 7)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 2, 2, 2, 0, 2, 1],
                    [2, 2, 2, 0, 2, 1],
                    [2, 2, 0, 2, 1],
                    [2, 0, 2, 1],
                    [0, 0, 0],
                    [3, 1],
                    [1],
                ]
            ),
        )

    @snapshot_clickhouse_queries
    def test_retention_event_action(self):
        _create_person(team=self.team, distinct_ids=["person1", "alias1"])
        _create_person(team=self.team, distinct_ids=["person2"])

        action = _create_signup_actions(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(3)),
                ("person2", _date(0)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
            ],
        )

        some_event = "$some_event"
        _create_events(self.team, [("person1", _date(3)), ("person2", _date(5))], some_event)

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(6, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 7,
                    "targetEntity": {
                        "id": action.pk,
                        "name": action.name,
                        "type": TREND_FILTER_TYPE_ACTIONS,
                    },
                    "returningEntity": {
                        "id": some_event,
                        "name": some_event,
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                },
            }
        )

        self.assertEqual(len(result), 7)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 0, 0, 1, 0, 1, 0],
                    [2, 0, 1, 0, 1, 0],
                    [2, 1, 0, 1, 0],
                    [2, 0, 1, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_first_time_retention(self):
        self._create_first_time_retention_events()

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=6)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_TIME,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
            }
        )

        self.assertEqual(len(result), 7)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 1, 2, 2, 1, 0, 1],
                    [1, 1, 0, 1, 1, 1],
                    [0, 0, 0, 0, 0],
                    [1, 1, 0, 1],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_first_time_retention_weeks(self):
        self._create_first_time_retention_events()

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=6)},
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_TIME,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
            }
        )

        self.assertEqual(len(result), 7)

        self.assertEqual(
            pluck(result, "values", "count"),
            pad([[0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0], [4, 4], [0]]),
        )

    def test_retention_with_properties(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 11,
                },
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$some_property",
                                    "operator": "exact",
                                    "value": ["value"],
                                }
                            ],
                        }
                    ],
                },
            }
        )
        self.assertEqual(len(result), 11)
        self.assertEqual(
            pluck(result, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0],
                    [1, 0, 1, 0, 0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 1, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_retention_with_properties_on_start_event(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        # only even indexed events have $some_property set
        _create_events(
            self.team,
            [
                ("person1", _date(0), {"$target_event_property": "value"}),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=0)},
                "retentionFilter": {
                    "targetEntity": {
                        "id": "$pageview",
                        "properties": [
                            {
                                "key": "$target_event_property",
                                "type": "event",
                                "operator": "exact",
                                "value": ["value"],
                            }
                        ],
                    },
                    "totalIntervals": 11,
                },
            }
        )
        self.assertEqual(len(result), 11)
        self.assertEqual(
            pluck(result, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_retention_with_properties_on_start_event_for_first_time(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        # only even indexed events have $some_property set
        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2), {"$target_event_property": "value"}),
                ("person1", _date(5), {"$target_event_property": "value"}),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=0)},
                "retentionFilter": {
                    "retentionType": "retention_first_time",
                    "totalIntervals": 11,
                    "targetEntity": {
                        "id": "$pageview",
                        "properties": [
                            {
                                "key": "$target_event_property",
                                "type": "event",
                                "operator": "exact",
                                "value": ["value"],
                            }
                        ],
                    },
                },
            }
        )
        self.assertEqual(len(result), 11)
        self.assertEqual(
            pluck(result, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 1, 1, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_retention_with_properties_on_return_event(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        # only even indexed events have $some_property set
        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1), {"$target_event_property": "value"}),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 11,
                    "returningEntity": {
                        "id": "$pageview",
                        "properties": [
                            {
                                "key": "$target_event_property",
                                "type": "event",
                                "operator": "exact",
                                "value": ["value"],
                            }
                        ],
                    },
                },
            }
        )
        self.assertEqual(len(result), 11)
        self.assertEqual(
            pluck(result, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],  # only one match, 1 day after for person 1
                    [2, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_retention_with_properties_on_return_event_with_first_time(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        # only even indexed events have $some_property set
        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5), {"$target_event_property": "value"}),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=0)},
                "retentionFilter": {
                    "retentionType": "retention_first_time",
                    "totalIntervals": 11,
                    "returningEntity": {
                        "id": "$pageview",
                        "properties": [
                            {
                                "key": "$target_event_property",
                                "type": "event",
                                "operator": "exact",
                                "value": ["value"],
                            }
                        ],
                    },
                },
            }
        )
        self.assertEqual(len(result), 11)
        self.assertEqual(
            pluck(result, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],  # only one match, 5 days after for person 1
                    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_retention_with_user_properties(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(6, hour=0)},
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "operator": "exact",
                                    "type": "person",
                                    "value": ["person1@test.com"],
                                }
                            ],
                        }
                    ],
                },
                "retentionFilter": {
                    "totalIntervals": 7,
                },
            }
        )

        self.assertEqual(len(result), 7)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1],
                    [1, 1, 0, 0, 1, 1],
                    [1, 0, 0, 1, 1],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [1, 1],
                    [1],
                ]
            ),
        )

    def test_retention_with_user_properties_and_minimum_occurrences(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )
        minimum_occurrences = 2

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ]
            * minimum_occurrences,
        )

        # Single event added to day 4 to ensure minimum occurrences check will exclude it.
        _create_events(self.team, [("person1", _date(3))])

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(6, hour=0)},
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "operator": "exact",
                                    "type": "person",
                                    "value": ["person1@test.com"],
                                }
                            ],
                        }
                    ],
                },
                "retentionFilter": {
                    "totalIntervals": 7,
                    "minimumOccurrences": minimum_occurrences,
                },
            }
        )

        self.assertEqual(len(result), 7)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))
        self.assertEqual(
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1],
                    [1, 1, 0, 0, 1, 1],
                    [1, 0, 0, 1, 1],
                    [1, 0, 1, 1],
                    [0, 0, 0],
                    [1, 1],
                    [1],
                ]
            ),
            pluck(result, "values", "count"),
        )

    @snapshot_clickhouse_queries
    def test_retention_with_user_properties_via_action(self):
        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {
                    "event": "$pageview",
                    "properties": [{"key": "email", "value": "person1@test.com", "type": "person"}],
                },
                {"event": "non_matching_event"},
            ],
        )

        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1", "alias1"],
            properties={"email": "person1@test.com"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person2"],
            properties={"email": "person2@test.com"},
        )

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(6, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 7,
                    "targetEntity": {"id": action.pk, "name": action.name, "type": TREND_FILTER_TYPE_ACTIONS},
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
            }
        )

        self.assertEqual(len(result), 7)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1],
                    [1, 1, 0, 0, 1, 1],
                    [1, 0, 0, 1, 1],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [1, 1],
                    [1],
                ]
            ),
        )

    def test_retention_action_start_point(self):
        _create_person(team=self.team, distinct_ids=["person1", "alias1"])
        _create_person(team=self.team, distinct_ids=["person2"])

        action = _create_signup_actions(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(6, hour=0)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "targetEntity": {"id": action.pk, "name": action.name, "type": TREND_FILTER_TYPE_ACTIONS},
                    "returningEntity": {"id": action.pk, "name": action.name, "type": TREND_FILTER_TYPE_ACTIONS},
                },
            }
        )

        self.assertEqual(len(result), 7)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1],
                    [2, 2, 1, 0, 1, 2],
                    [2, 1, 0, 1, 2],
                    [1, 0, 0, 1],
                    [0, 0, 0],
                    [1, 1],
                    [2],
                ]
            ),
        )

    def test_filter_test_accounts(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person1", "alias1"],
            properties={"email": "test@posthog.com"},
        )
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "filterTestAccounts": True,
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            }
        )
        self.assertEqual(len(result), 11)
        self.assertEqual(
            pluck(result, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 1, 0, 0, 1, 0, 0, 0, 0],
                    [1, 1, 0, 0, 1, 0, 0, 0, 0],
                    [1, 0, 0, 1, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def _create_first_time_retention_events(self):
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        p2 = _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        p3 = _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        p4 = _create_person(team_id=self.team.pk, distinct_ids=["person4"])
        _create_person(team_id=self.team.pk, distinct_ids=["shouldnt_include"])

        _create_events(
            self.team,
            [
                ("shouldnt_include", _date(-5)),
                ("shouldnt_include", _date(-1)),
                ("person1", _date(-1)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(3)),
                ("person1", _date(4)),
                ("person2", _date(-1)),
            ],
            "$user_signed_up",
        )

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        _create_events(self.team, [("person3", _date(0))], "$user_signed_up")

        _create_events(
            self.team,
            [
                ("person3", _date(1)),
                ("person3", _date(3)),
                ("person3", _date(4)),
                ("person3", _date(5)),
            ],
        )

        _create_events(self.team, [("person4", _date(2))], "$user_signed_up")

        _create_events(self.team, [("person4", _date(3)), ("person4", _date(5))])

        return p1, p2, p3, p4

    @snapshot_clickhouse_queries
    def test_timezones(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(-1, 1)),
                ("person1", _date(0, 1)),
                (
                    "person1",
                    _date(1, 1),
                ),  # this is the only event in US Pacific on the first day
                ("person2", _date(6, 1)),
                ("person2", _date(6, 9)),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            }
        )

        self.team.timezone = "US/Pacific"
        self.team.save()

        result_pacific = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            }
        )

        self.assertEqual(
            pluck(result_pacific, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )

        self.assertEqual(
            result_pacific[0]["date"],
            datetime(2020, 6, 10, tzinfo=ZoneInfo("US/Pacific")),
        )
        self.assertEqual(result_pacific[0]["date"].isoformat(), "2020-06-10T00:00:00-07:00")

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0],  # person 2
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

        self.assertEqual(
            pluck(result_pacific, "values", "count"),
            pad(
                [
                    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 0, 0, 0, 0],  # person 2 is across two dates in US/Pacific
                    [1, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    @snapshot_clickhouse_queries
    def test_day_interval_sampled(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person1", _date(5)),
                ("alias1", _date(5, 9)),
                ("person1", _date(6)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person2", _date(3)),
                ("person2", _date(6)),
            ],
        )

        # even if set to hour 6 it should default to beginning of day and include all pageviews above
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, hour=6)},
                "samplingFactor": 1,
                "retentionFilter": {
                    "totalIntervals": 11,
                },
            }
        )
        self.assertEqual(len(result), 11)
        self.assertEqual(
            pluck(result, "label"),
            [
                "Day 0",
                "Day 1",
                "Day 2",
                "Day 3",
                "Day 4",
                "Day 5",
                "Day 6",
                "Day 7",
                "Day 8",
                "Day 9",
                "Day 10",
            ],
        )
        self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0],
                    [2, 2, 1, 0, 1, 2, 0, 0, 0, 0],
                    [2, 1, 0, 1, 2, 0, 0, 0, 0],
                    [1, 0, 0, 1, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0, 0],
                    [1, 1, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ]
            ),
        )

    def test_retention_with_breakdown_with_person_properties(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"country": "US"})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"country": "UK"})
        _create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={"country": "US"})
        _create_person(team_id=self.team.pk, distinct_ids=["person4"], properties={"country": "Germany"})

        _create_events(
            self.team,
            [
                # US cohort
                ("person1", _date(0)),  # Day 0
                ("person1", _date(1)),  # Day 1
                ("person1", _date(3)),  # Day 3
                ("person3", _date(0)),  # Day 0
                ("person3", _date(2)),  # Day 2
                # UK cohort
                ("person2", _date(0)),  # Day 0
                ("person2", _date(1)),  # Day 1
                ("person2", _date(4)),  # Day 4
                # Germany cohort
                ("person4", _date(0)),  # Day 0
                ("person4", _date(5)),  # Day 5
            ],
        )

        # Run query with breakdown by country
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                },
                "breakdownFilter": {"breakdowns": [{"property": "country", "type": "person"}]},
            }
        )

        # Verify we have results for each country
        breakdown_values = {c.get("breakdown_value") for c in result}

        self.assertEqual(breakdown_values, {"Germany", "UK", "US"})

        # Verify US cohort data
        us_cohorts = pluck([c for c in result if c.get("breakdown_value") == "US"], "values", "count")

        self.assertEqual(
            us_cohorts,
            pad(
                [
                    [2, 1, 1, 1, 0, 0],
                    [1, 0, 1, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

        uk_cohorts = pluck([c for c in result if c.get("breakdown_value") == "UK"], "values", "count")
        self.assertEqual(
            uk_cohorts,
            pad(
                [
                    [1, 1, 0, 0, 1, 0],
                    [1, 0, 0, 1, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

        germany_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Germany"], "values", "count")
        self.assertEqual(
            germany_cohorts,
            pad(
                [
                    [1, 0, 0, 0, 0, 1],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                ]
            ),
        )

    def test_retention_actor_query_with_breakdown(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"country": "US"})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"country": "UK"})
        _create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={"country": "US"})

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person1", _date(1)),
                ("person1", _date(2)),
                ("person2", _date(0)),
                ("person2", _date(1)),
                ("person2", _date(2)),
                ("person3", _date(0)),
                ("person3", _date(1)),
            ],
        )

        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(2, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 3,
                    "period": "Day",
                },
                "breakdownFilter": {"breakdowns": [{"property": "country", "type": "person"}]},
            },
            breakdown=["US"],
        )

        # Should only return the US persons
        self.assertEqual(len(result), 2)

        person1_us = next(r for r in result if "person1" in r[0]["distinct_ids"])
        person3_us = next(r for r in result if "person3" in r[0]["distinct_ids"])

        # counts are index 1
        self.assertEqual(person1_us[1], [0, 1, 2])
        self.assertEqual(person3_us[1], [0, 1])

        result = self.run_actors_query(
            interval=1,
            query={
                "dateRange": {"date_to": _date(2, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 3,
                    "period": "Day",
                },
                "breakdownFilter": {"breakdowns": [{"property": "country", "type": "person"}]},
            },
            breakdown=["UK"],
        )

        person2_uk = next(r for r in result if "person2" in r[0]["distinct_ids"])
        self.assertEqual(person2_uk[1], [0, 1])

    def test_retention_actor_query_with_breakdown_and_minimum_occurrences(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"country": "US"})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"country": "UK"})
        _create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={"country": "US"})
        minimum_occurrences = 2

        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                *[("person1", _date(1))] * minimum_occurrences,
                *[("person1", _date(2))] * minimum_occurrences,
                ("person1", _date(3)),  # Shouldn't show up as as return event as it occurred < minimum_occurrences
                ("person2", _date(0)),
                *[("person2", _date(1))] * minimum_occurrences,
                *[("person2", _date(2))] * minimum_occurrences,
                ("person2", _date(3)),  # Shouldn't show up as occurred < minimum_occurrences
                ("person3", _date(0)),
                *[("person3", _date(1))] * minimum_occurrences,
                ("person3", _date(3)),  # Shouldn't show up as as return event as it occurred < minimum_occurrences
            ],
        )

        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(2, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 3,
                    "period": "Day",
                    "minimumOccurrences": minimum_occurrences,
                },
                "breakdownFilter": {"breakdowns": [{"property": "country", "type": "person"}]},
            },
            breakdown=["US"],
        )

        # Should only return the US persons
        self.assertEqual(len(result), 2)

        person1_us = next(r for r in result if "person1" in r[0]["distinct_ids"])
        person3_us = next(r for r in result if "person3" in r[0]["distinct_ids"])

        # counts are index 1
        self.assertEqual(person1_us[1], [0, 1, 2])
        self.assertEqual(person3_us[1], [0, 1])

        result = self.run_actors_query(
            interval=1,
            query={
                "dateRange": {"date_to": _date(2, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 3,
                    "period": "Day",
                    "minimumOccurrences": minimum_occurrences,
                },
                "breakdownFilter": {"breakdowns": [{"property": "country", "type": "person"}]},
            },
            breakdown=["UK"],
        )

        person2_uk = next(r for r in result if "person2" in r[0]["distinct_ids"])
        self.assertEqual(person2_uk[1], [0, 1])

    def test_retention_with_breakdown_event_properties(self):
        """Test retention with breakdown by event properties"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        # Create events with different browser properties
        _create_events(
            self.team,
            [
                # Chrome cohort
                ("person1", _date(0), {"browser": "Chrome"}),  # Day 0
                ("person1", _date(1), {"browser": "Chrome"}),  # Day 1
                ("person1", _date(3), {"browser": "Chrome"}),  # Day 3
                ("person3", _date(0), {"browser": "Chrome"}),  # Day 0
                ("person3", _date(2), {"browser": "Chrome"}),  # Day 2
                # Safari cohort
                ("person2", _date(0), {"browser": "Safari"}),  # Day 0
                ("person2", _date(1), {"browser": "Safari"}),  # Day 1
                ("person2", _date(4), {"browser": "Safari"}),  # Day 4
                # Firefox cohort
                ("person4", _date(0), {"browser": "Firefox"}),  # Day 0
                ("person4", _date(5), {"browser": "Firefox"}),  # Day 5
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                },
                "breakdownFilter": {"breakdowns": [{"property": "browser", "type": "event"}]},
            }
        )

        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {"Chrome", "Safari", "Firefox"})

        chrome_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Chrome"], "values", "count")

        self.assertEqual(
            chrome_cohorts,
            pad(
                [
                    [2, 1, 1, 1, 0, 0],
                    [1, 0, 1, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

        safari_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Safari"], "values", "count")
        self.assertEqual(
            safari_cohorts,
            pad(
                [
                    [1, 1, 0, 0, 1, 0],
                    [1, 0, 0, 1, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

        firefox_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Firefox"], "values", "count")
        self.assertEqual(
            firefox_cohorts,
            pad(
                [
                    [1, 0, 0, 0, 0, 1],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                ]
            ),
        )

    def test_retention_with_breakdown_event_properties_and_minimum_occurrences(self):
        """Test retention with breakdown by event properties"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])
        minimum_occurrences = 2

        # Create events with different browser properties
        _create_events(
            self.team,
            [
                # Chrome cohort
                ("person1", _date(0), {"browser": "Chrome"}),  # Day 0
                ("person1", _date(1), {"browser": "Chrome"}),  # Day 1
                ("person1", _date(3), {"browser": "Chrome"}),  # Day 3
                ("person3", _date(0), {"browser": "Chrome"}),  # Day 0
                ("person3", _date(2), {"browser": "Chrome"}),  # Day 2
                # Safari cohort
                ("person2", _date(0), {"browser": "Safari"}),  # Day 0
                ("person2", _date(1), {"browser": "Safari"}),  # Day 1
                ("person2", _date(4), {"browser": "Safari"}),  # Day 4
                # Firefox cohort
                ("person4", _date(0), {"browser": "Firefox"}),  # Day 0
                ("person4", _date(5), {"browser": "Firefox"}),  # Day 5
            ]
            * 2,
        )

        # Create events that happened a single time to ensure minimum occurrences filter is working
        _create_events(
            self.team,
            [
                ("person1", _date(5), {"browser": "Chrome"}),
                ("person2", _date(2), {"browser": "Safari"}),
                ("person3", _date(3), {"browser": "Chrome"}),
                ("person4", _date(3), {"browser": "Firefox"}),
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                    "minimumOccurrences": minimum_occurrences,
                },
                "breakdownFilter": {"breakdowns": [{"property": "browser", "type": "event"}]},
            }
        )

        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {"Chrome", "Safari", "Firefox"})

        chrome_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Chrome"], "values", "count")

        self.assertEqual(
            pad(
                [
                    [2, 1, 1, 1, 0, 0],
                    [1, 0, 1, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [2, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                ]
            ),
            chrome_cohorts,
        )

        safari_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Safari"], "values", "count")
        self.assertEqual(
            pad(
                [
                    [1, 1, 0, 0, 1, 0],
                    [1, 0, 0, 1, 0, 0],
                    [1, 0, 1, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
            safari_cohorts,
        )

        firefox_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Firefox"], "values", "count")
        self.assertEqual(
            pad(
                [
                    [1, 0, 0, 0, 0, 1],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 1, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                ]
            ),
            firefox_cohorts,
        )

    def test_retention_actor_query_with_event_property_breakdown(self):
        """Test actor query with event property breakdown filter"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])

        _create_events(
            self.team,
            [
                ("person1", _date(0), {"browser": "Chrome"}),
                ("person1", _date(1), {"browser": "Chrome"}),
                ("person1", _date(2), {"browser": "Chrome"}),
                ("person2", _date(0), {"browser": "Safari"}),
                ("person2", _date(1), {"browser": "Safari"}),
                ("person2", _date(2), {"browser": "Safari"}),
                ("person3", _date(0), {"browser": "Chrome"}),
                ("person3", _date(1), {"browser": "Chrome"}),
            ],
        )

        # Test Chrome breakdown
        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(2, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 3,
                    "period": "Day",
                },
                "breakdownFilter": {"breakdowns": [{"property": "browser", "type": "event"}]},
            },
            breakdown=["Chrome"],
        )

        # Should only return the Chrome people
        self.assertEqual(len(result), 2)

        person1_chrome = next(r for r in result if "person1" in r[0]["distinct_ids"])
        person3_chrome = next(r for r in result if "person3" in r[0]["distinct_ids"])

        # counts are index 1
        self.assertEqual(person1_chrome[1], [0, 1, 2])
        self.assertEqual(person3_chrome[1], [0, 1])

        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(2, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 3,
                    "period": "Day",
                },
                "breakdownFilter": {"breakdowns": [{"property": "browser", "type": "event"}]},
            },
            breakdown=["Safari"],
        )

        self.assertEqual(len(result), 1)

        person2_safari = next(r for r in result if "person2" in r[0]["distinct_ids"])

        self.assertEqual(person2_safari[1], [0, 1, 2])

    def test_retention_with_breakdown_different_entities(self):
        """Test retention with breakdown by event properties where target and returning entities are different"""
        # Create people
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        # Create signup events (target entity)
        _create_events(
            self.team,
            [
                # Clothing category
                ("person1", _date(0), {"category": "clothing", "$event_type": "signup"}),
                ("person2", _date(0), {"category": "clothing", "$event_type": "signup"}),
                # Electronics category
                ("person3", _date(0), {"category": "electronics", "$event_type": "signup"}),
                ("person4", _date(1), {"category": "electronics", "$event_type": "signup"}),
            ],
            event="signup",
        )

        # Create purchase events (returning entity)
        _create_events(
            self.team,
            [
                # Person1 makes purchases on day 1, 3, 5
                ("person1", _date(1), {"category": "clothing", "$event_type": "purchase"}),
                # this event ignored as doesn't have same breakdown value as start event
                ("person1", _date(3), {"$event_type": "purchase"}),
                # this event ignored as doesn't have same breakdown value as start event
                ("person1", _date(5), {"category": "electronics", "$event_type": "purchase"}),
                # Person2 makes purchase on day 2
                ("person2", _date(2), {"category": "clothing", "$event_type": "purchase"}),
                # Person3 makes purchases on day 1, 4
                ("person3", _date(1), {"category": "electronics", "$event_type": "purchase"}),
                ("person3", _date(4), {"category": "electronics", "$event_type": "purchase"}),
                # Person4 makes purchases on day 1, 4
                # this event ignored as on same day as signup
                ("person4", _date(1), {"category": "electronics", "$event_type": "purchase"}),
                ("person4", _date(2), {"category": "electronics", "$event_type": "purchase"}),
                # this event ignored as doesn't have same breakdown value as start event
                ("person4", _date(3), {"category": "clothing", "$event_type": "purchase"}),
            ],
            event="purchase",
        )

        # Define entities
        target_entity = {"id": "signup", "type": "events"}
        returning_entity = {"id": "purchase", "type": "events"}

        # Run query with breakdown by category
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                    "targetEntity": target_entity,
                    "returningEntity": returning_entity,
                },
                "breakdownFilter": {"breakdowns": [{"property": "category", "type": "event"}]},
            }
        )

        # Verify we have results for each category
        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {"clothing", "electronics"})

        clothing_cohorts = pluck([c for c in result if c.get("breakdown_value") == "clothing"], "values", "count")
        self.assertEqual(
            clothing_cohorts,
            pad(
                [
                    [2, 1, 1, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

        electronics_cohorts = pluck([c for c in result if c.get("breakdown_value") == "electronics"], "values", "count")
        self.assertEqual(
            electronics_cohorts,
            pad(
                [
                    [1, 1, 0, 0, 1, 0],
                    [1, 1, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

        result = self.run_actors_query(
            interval=1,
            query={
                "dateRange": {"date_to": _date(5, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                    "targetEntity": target_entity,
                    "returningEntity": returning_entity,
                },
                "breakdownFilter": {"breakdowns": [{"property": "category", "type": "event"}]},
            },
            breakdown=["electronics"],
        )

        person4_electronics = next(r for r in result if "person4" in r[0]["distinct_ids"])
        self.assertEqual(person4_electronics[1], [0, 1])

        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(5, hour=10)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                    "targetEntity": target_entity,
                    "returningEntity": returning_entity,
                },
                "breakdownFilter": {"breakdowns": [{"property": "category", "type": "event"}]},
            },
            breakdown=["clothing"],
        )

        person1_clothing = next(r for r in result if "person1" in r[0]["distinct_ids"])
        self.assertEqual(person1_clothing[1], [0, 1])

        person2_clothing = next(r for r in result if "person2" in r[0]["distinct_ids"])
        self.assertEqual(person2_clothing[1], [0, 2])

    def test_retention_with_breakdown_event_metadata(self):
        """Test retention with breakdown by event metadata"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person4"])

        GroupTypeMapping.objects.create(
            team_id=self.team.pk,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        # Create events with different groups
        _create_events(
            self.team,
            [
                # Apple cohort
                ("person1", _date(0), {"$group_0": "Apple"}),  # Day 0
                ("person1", _date(1), {"$group_0": "Apple"}),  # Day 1
                ("person1", _date(3), {"$group_0": "Apple"}),  # Day 3
                ("person3", _date(0), {"$group_0": "Apple"}),  # Day 0
                ("person3", _date(2), {"$group_0": "Apple"}),  # Day 2
                # Google cohort
                ("person2", _date(0), {"$group_0": "Google"}),  # Day 0
                ("person2", _date(1), {"$group_0": "Google"}),  # Day 1
                ("person2", _date(4), {"$group_0": "Google"}),  # Day 4
                # Stripe cohort
                ("person4", _date(0), {"$group_0": "Stripe"}),  # Day 0
                ("person4", _date(5), {"$group_0": "Stripe"}),  # Day 5
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                },
                "breakdownFilter": {"breakdowns": [{"property": "$group_0", "type": "event_metadata"}]},
            }
        )

        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {"Apple", "Google", "Stripe"})

        apple_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Apple"], "values", "count")

        self.assertEqual(
            apple_cohorts,
            pad(
                [
                    [2, 1, 1, 1, 0, 0],
                    [1, 0, 1, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

    def test_retention_with_breakdown_on_start_event(self):
        """Test retention with breakdown by event properties where target and returning entities are different"""
        # Create people
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])

        # Create signup events (target entity)
        _create_events(
            self.team,
            [
                ("person1", _date(0), {"category": "clothing", "$event_type": "signup"}),
                ("person2", _date(0), {"category": "clothing", "$event_type": "signup"}),
                ("person3", _date(0), {"category": "electronics", "$event_type": "signup"}),
            ],
            event="signup",
        )

        # Create purchase events (returning entity)
        _create_events(
            self.team,
            [
                # Person1 makes purchases on day 1, 3, 5
                ("person1", _date(1), {"$event_type": "purchase"}),
                ("person1", _date(3), {"$event_type": "purchase"}),
                ("person1", _date(5), {"$event_type": "purchase"}),
                # Person2 makes purchase on day 2
                ("person2", _date(2), {"$event_type": "purchase"}),
                # Person3 makes purchases on day 1, 4
                ("person3", _date(1), {"$event_type": "purchase"}),
                ("person3", _date(4), {"$event_type": "purchase"}),
                # Person4 makes purchases on day 1, 4
                ("person4", _date(1), {"$event_type": "purchase"}),
                ("person4", _date(4), {"$event_type": "purchase"}),
            ],
            event="purchase",
        )

        # Define entities
        target_entity = {"id": "signup", "type": "events"}
        returning_entity = {"id": "purchase", "type": "events"}

        # Run query with breakdown by category
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                    "targetEntity": target_entity,
                    "returningEntity": returning_entity,
                },
                "breakdownFilter": {"breakdowns": [{"property": "category", "type": "event"}]},
            }
        )

        # Verify we have results for each category
        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {"clothing", "electronics"})

        # none of the return events have the same breakdown value so
        # they won't get counted
        clothing_cohorts = pluck([c for c in result if c.get("breakdown_value") == "clothing"], "values", "count")
        self.assertEqual(
            clothing_cohorts,
            pad(
                [
                    [2, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

    def test_events_query(self):
        # Create test people
        person1 = _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        person2 = _create_person(team_id=self.team.pk, distinct_ids=["person2"])

        # Create test events across different days
        _create_events(
            self.team,
            [
                # Person 1 events - active in day 0, 1, 2, 5, 6
                ("person1", _date(0)),  # Day 0 - start event
                ("person1", _date(1)),  # Day 1 - return event
                ("person1", _date(2)),  # Day 2 - return event
                ("person1", _date(5)),  # Day 5 - return event
                ("alias1", _date(5, 9)),  # Day 5 - also a return event (alias)
                ("person1", _date(6)),  # Day 6 - return event
                # Person 2 events - active in day 1, 2, 3, 6
                ("person2", _date(1)),  # Day 1 - start event (not day 0)
                ("person2", _date(2)),  # Day 2 - return event
                ("person2", _date(3)),  # Day 3 - return event
                ("person2", _date(6)),  # Day 6 - return event
            ],
        )

        # Set up the query
        query = RetentionQuery(
            dateRange={"date_to": _date(6, hour=6)},
            retentionFilter={
                "totalIntervals": 7,
                "period": "Day",
            },
        )

        # Create the query runner
        runner = RetentionQueryRunner(team=self.team, query=query)

        # Get events query for interval 0 (day 0) and person1
        events_query = runner.to_events_query(interval=0, person_id=person1.uuid)

        # Execute the query
        response = execute_hogql_query(
            query_type="RetentionEventsQuery",
            query=events_query,
            team=self.team,
        )

        # Get the results
        results = response.results

        # Verify we get both start and return events
        self.assertTrue(len(results) > 0, "Expected events to be returned")

        # Check that we have at least one start event
        start_events = [row for row in results if row[5] == "start_event"]
        self.assertTrue(len(start_events) > 0, "Expected at least one start event")

        # Check that we have at least one return event
        return_events = [row for row in results if row[5] == "return_event"]
        self.assertTrue(len(return_events) > 0, "Expected at least one return event")

        # Get specific event types from the results
        event_timestamps = [(row[0], row[5]) for row in results]

        # Verify the timestamps match what we expect
        expected_timestamps = [
            # Start event on day 0
            (_date(0), "start_event"),
            # Return events on days 1, 2, 5, 6
            (_date(1), "return_event"),
            (_date(2), "return_event"),
            (_date(5), "return_event"),
            (_date(5, 9), "return_event"),
            (_date(6), "return_event"),
        ]

        # Check that each expected timestamp is in the results
        for expected_time, expected_type in expected_timestamps:
            self.assertTrue(
                any(
                    datetime.fromisoformat(expected_time).date() == actual_time.date() and expected_type == actual_type
                    for actual_time, actual_type in event_timestamps
                ),
                f"Missing expected {expected_type} at {expected_time}",
            )

        # Test with a different interval - interval 1 should only return person2
        events_query_day1 = runner.to_events_query(interval=1, person_id=person2.uuid)
        response_day1 = execute_hogql_query(
            query_type="RetentionEventsQuery",
            query=events_query_day1,
            team=self.team,
        )
        results_day1 = response_day1.results

        # Verify we have events for person2 on day 1
        self.assertTrue(len(results_day1) > 0, "Expected events for day 1")

        # Check timestamps for day 1 events
        day1_event_timestamps = [(row[0], row[5]) for row in results_day1]

        # Expected timestamps for person2
        expected_day1_timestamps = [
            # Start event on day 1
            (_date(1), "start_event"),
            # Return events on days 2, 3, 6
            (_date(2), "return_event"),
            (_date(3), "return_event"),
            (_date(6), "return_event"),
        ]

        # Check that each expected timestamp is in the day 1 results
        for expected_time, expected_type in expected_day1_timestamps:
            self.assertTrue(
                any(
                    datetime.fromisoformat(expected_time).date() == actual_time.date() and expected_type == actual_type
                    for actual_time, actual_type in day1_event_timestamps
                ),
                f"Missing expected {expected_type} at {expected_time} for person2 on day 1",
            )


class TestClickhouseRetentionGroupAggregation(ClickhouseTestMixin, APIBaseTest):
    def run_query(self, query, *, limit_context: Optional[LimitContext] = None):
        if not query.get("retentionFilter"):
            query["retentionFilter"] = {}
        runner = RetentionQueryRunner(team=self.team, query=query, limit_context=limit_context)
        return runner.calculate().model_dump()["results"]

    def run_actors_query(self, interval, query, select=None, actor="person"):
        query["kind"] = "RetentionQuery"
        if not query.get("retentionFilter"):
            query["retentionFilter"] = {}
        runner = ActorsQueryRunner(
            team=self.team,
            query={
                "select": [actor, "appearances", *(select or [])],
                "orderBy": ["length(appearances) DESC", "actor_id"],
                "source": {
                    "kind": "InsightActorsQuery",
                    "interval": interval,
                    "source": query,
                },
            },
        )
        return runner.calculate().model_dump()["results"]

    def _create_groups_and_events(self):
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.create(
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
            properties={},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:2",
            properties={},
        )

        Person.objects.create(team=self.team, distinct_ids=["person1", "alias1"])
        Person.objects.create(team=self.team, distinct_ids=["person2"])
        Person.objects.create(team=self.team, distinct_ids=["person3"])

        _create_events(
            self.team,
            [
                ("person1", _date(0), {"$group_0": "org:5", "$group_1": "company:1"}),
                ("person2", _date(0), {"$group_0": "org:6"}),
                ("person3", _date(0)),
                ("person1", _date(1), {"$group_0": "org:5"}),
                ("person2", _date(1), {"$group_0": "org:6"}),
                ("person1", _date(7), {"$group_0": "org:5"}),
                ("person2", _date(7), {"$group_0": "org:6"}),
                ("person1", _date(14), {"$group_0": "org:5"}),
                (
                    "person1",
                    _date(month=1, day=-6),
                    {"$group_0": "org:5", "$group_1": "company:1"},
                ),
                ("person2", _date(month=1, day=-6), {"$group_0": "org:6"}),
                ("person2", _date(month=1, day=1), {"$group_0": "org:6"}),
                ("person1", _date(month=1, day=1), {"$group_0": "org:5"}),
                (
                    "person2",
                    _date(month=1, day=15),
                    {"$group_0": "org:6", "$group_1": "company:1"},
                ),
            ],
        )

    @snapshot_clickhouse_queries
    def test_groups_aggregating(self):
        self._create_groups_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, month=1, hour=0)},
                "aggregation_group_type_index": 0,
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                },
            }
        )
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 2, 1, 2, 2, 0, 1],
                    [2, 1, 2, 2, 0, 1],
                    [1, 1, 1, 0, 0],
                    [2, 2, 0, 1],
                    [2, 0, 1],
                    [0, 0],
                    [1],
                ]
            ),
        )

        actor_result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(10, month=1, hour=0)},
                "aggregation_group_type_index": 0,
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                },
            },
            actor="group",
        )
        self.assertCountEqual([actor[0]["id"] for actor in actor_result], ["org:5", "org:6"])

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, month=1, hour=0)},
                "aggregation_group_type_index": 1,
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                },
            }
        )
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 0, 0, 1, 0, 0, 1],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0],
                    [1, 0, 0, 1],
                    [0, 0, 0],
                    [0, 0],
                    [1],
                ]
            ),
        )

    def test_groups_in_period(self):
        self._create_groups_and_events()

        actor_result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(10, month=1, hour=0)},
                "aggregation_group_type_index": 0,
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                },
            },
            actor="group",
        )

        self.assertEqual(actor_result[0][0]["id"], "org:5")
        self.assertEqual(actor_result[0][1], [0, 1, 2, 3, 4])

        self.assertEqual(actor_result[1][0]["id"], "org:6")
        self.assertEqual(actor_result[1][1], [0, 1, 3, 4, 6])

    @snapshot_clickhouse_queries
    def test_groups_aggregating_person_on_events(self):
        self._create_groups_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, month=1, hour=0)},
                "aggregation_group_type_index": 0,
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                },
            }
        )
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 2, 1, 2, 2, 0, 1],
                    [2, 1, 2, 2, 0, 1],
                    [1, 1, 1, 0, 0],
                    [2, 2, 0, 1],
                    [2, 0, 1],
                    [0, 0],
                    [1],
                ]
            ),
        )

        actor_result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(10, month=1, hour=0)},
                "aggregation_group_type_index": 0,
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                },
            },
            actor="group",
        )

        self.assertCountEqual([actor[0]["id"] for actor in actor_result], ["org:5", "org:6"])

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(10, month=1, hour=0)},
                "aggregation_group_type_index": 1,
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 7,
                },
            }
        )
        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [1, 0, 0, 1, 0, 0, 1],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0],
                    [1, 0, 0, 1],
                    [0, 0, 0],
                    [0, 0],
                    [1],
                ]
            ),
        )

    @patch("posthog.hogql.query.sync_execute", wraps=sync_execute)
    def test_limit_is_context_aware(self, mock_sync_execute: MagicMock):
        self.run_query(query={}, limit_context=LimitContext.QUERY_ASYNC)

        mock_sync_execute.assert_called_once()
        self.assertIn(f" max_execution_time={HOGQL_INCREASED_MAX_EXECUTION_TIME},", mock_sync_execute.call_args[0][0])

    def test_retention_with_breakdown_limit(self):
        _create_person(team_id=self.team.pk, distinct_ids=["p_chrome_1"])
        _create_person(team_id=self.team.pk, distinct_ids=["p_chrome_2"])
        _create_person(team_id=self.team.pk, distinct_ids=["p_chrome_3"])
        _create_person(team_id=self.team.pk, distinct_ids=["p_safari_1"])
        _create_person(team_id=self.team.pk, distinct_ids=["p_safari_2"])
        _create_person(team_id=self.team.pk, distinct_ids=["p_firefox_1"])
        _create_person(team_id=self.team.pk, distinct_ids=["p_edge_1"])

        # Create events with different browser properties
        _create_events(
            self.team,
            [
                # Chrome cohort (largest - 3 people)
                ("p_chrome_1", _date(0), {"browser": "Chrome"}),
                ("p_chrome_1", _date(1), {"browser": "Chrome"}),  # Day 1 return
                ("p_chrome_2", _date(0), {"browser": "Chrome"}),
                ("p_chrome_2", _date(2), {"browser": "Chrome"}),  # Day 2 return
                ("p_chrome_3", _date(0), {"browser": "Chrome"}),
                # Safari cohort (second largest - 2 people)
                ("p_safari_1", _date(0), {"browser": "Safari"}),
                ("p_safari_1", _date(1), {"browser": "Safari"}),  # Day 1 return
                ("p_safari_2", _date(0), {"browser": "Safari"}),
                # Firefox cohort (small - 1 person)
                ("p_firefox_1", _date(0), {"browser": "Firefox"}),
                ("p_firefox_1", _date(3), {"browser": "Firefox"}),  # Day 3 return
                # Edge cohort (small - 1 person)
                ("p_edge_1", _date(0), {"browser": "Edge"}),
                ("p_edge_1", _date(4), {"browser": "Edge"}),  # Day 4 return
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(5, hour=0)},
                "retentionFilter": {
                    "totalIntervals": 6,
                    "period": "Day",
                },
                "breakdownFilter": {
                    "breakdowns": [{"property": "browser", "type": "event"}],
                    "breakdown_limit": 2,  # Limit to top 2 browsers + Other
                },
            }
        )

        # 1. Check that breakdown values are Chrome, Safari, and Other
        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {"Chrome", "Safari", BREAKDOWN_OTHER_STRING_LABEL})

        # 2. Check Chrome counts (should be top cohort)
        chrome_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Chrome"], "values", "count")
        self.assertEqual(
            chrome_cohorts,
            pad(
                [
                    [3, 1, 1, 0, 0, 0],  # Day 0: 3 start, Day 1: 1 returns, Day 2: 1 returns
                    [1, 0, 0, 0, 0, 0],  # Day 1: p_chrome_1 event. No returns in subsequent intervals.
                    [1, 0, 0, 0, 0, 0],  # Day 2: p_chrome_2 event. No returns.
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

        # 3. Check Safari counts (should be second cohort)
        safari_cohorts = pluck([c for c in result if c.get("breakdown_value") == "Safari"], "values", "count")
        self.assertEqual(
            safari_cohorts,
            pad(
                [
                    [2, 1, 0, 0, 0, 0],  # Day 0: 2 start, Day 1: 1 returns
                    [1, 0, 0, 0, 0, 0],  # Day 1: (p_safari_1 started)
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

        # 4. Check "Other" counts (should be sum of Firefox + Edge)
        other_cohorts = pluck(
            [c for c in result if c.get("breakdown_value") == BREAKDOWN_OTHER_STRING_LABEL], "values", "count"
        )
        self.assertEqual(
            other_cohorts,
            pad(
                [
                    [
                        2,
                        0,
                        0,
                        1,
                        1,
                        0,
                    ],  # Day 0: 2 start (firefox+edge), Day 3: 1 returns (firefox), Day 4: 1 returns (edge)
                    [0, 0, 0, 0, 0, 0],
                    [0, 0, 0, 0, 0, 0],
                    [1, 0, 0, 0, 0, 0],  # Day 3: (p_firefox_1 started)
                    [1, 0, 0, 0, 0, 0],  # Day 4: (p_edge_1 started)
                    [0, 0, 0, 0, 0, 0],
                ]
            ),
        )

    def test_retention_with_virtual_person_property_breakdown(self):
        with freeze_time("2020-01-12T12:00:00Z"):
            # Create person with initial referring domain
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["p1"],
                properties={"$initial_referring_domain": "https://www.google.com"},
            )
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["p2"],
                properties={"$initial_referring_domain": "https://www.facebook.com"},
            )

            # Create events for both users
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-12T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-13T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="p2",
                timestamp="2020-01-12T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="p2",
                timestamp="2020-01-14T12:00:00Z",
            )

        result = self.run_query(
            {
                "dateRange": {
                    "date_from": "2020-01-12T00:00:00Z",
                    "date_to": "2020-01-19T00:00:00Z",
                },
                "retentionFilter": {
                    "targetEntity": {
                        "id": "$pageview",
                        "type": "events",
                    },
                    "returningEntity": {
                        "id": "$pageview",
                        "type": "events",
                    },
                    "totalIntervals": 7,
                    "period": "Day",
                },
                "breakdownFilter": {
                    "breakdowns": [
                        {
                            "type": "person",
                            "property": "$virt_initial_channel_type",
                        }
                    ],
                },
            }
        )

        results_by_breakdown: dict[str, list] = {}
        for r in result:
            breakdown_value = r["breakdown_value"]
            if breakdown_value not in results_by_breakdown:
                results_by_breakdown[breakdown_value] = []
            results_by_breakdown[breakdown_value].append(r)

        assert len(results_by_breakdown) == 2  # One for each channel type

        social_results = results_by_breakdown["Organic Social"]
        assert len(social_results) == 8  # 8 days
        assert social_results[0]["values"][0]["count"] == 1  # Day 0
        assert social_results[0]["values"][1]["count"] == 0  # Day 1
        assert social_results[0]["values"][2]["count"] == 1  # Day 2

        organic_results = results_by_breakdown["Organic Search"]
        assert len(organic_results) == 8  # 8 days
        assert organic_results[0]["values"][0]["count"] == 1  # Day 0
        assert organic_results[0]["values"][1]["count"] == 1  # Day 1
        assert organic_results[0]["values"][2]["count"] == 0  # Day 2
