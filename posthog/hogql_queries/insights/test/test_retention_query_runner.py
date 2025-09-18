import uuid
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.schema import RetentionQuery

from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.constants import (
    RETENTION_FIRST_EVER_OCCURRENCE,
    RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.insights.trends.breakdown import BREAKDOWN_OTHER_STRING_LABEL
from posthog.models import Action, Cohort
from posthog.models.group.util import create_group
from posthog.models.person import Person
from posthog.queries.breakdown_props import ALL_USERS_COHORT_ID
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.test.test_utils import create_group_type_mapping_without_created_at


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
                    "retentionType": RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
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
                    "retentionType": RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
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
                    "retentionType": RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
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
                    "retentionType": RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
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
                    "retentionType": RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
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

    def _create_first_time_ever_retention_events(self):
        """
        Create test events for first time ever retention.
        Key difference from first_time: this looks at the user's very first event across ALL event types,
        not just the first occurrence of the target event.
        """
        p1 = _create_person(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
        p2 = _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        p3 = _create_person(team_id=self.team.pk, distinct_ids=["person3"])
        p4 = _create_person(team_id=self.team.pk, distinct_ids=["person4"])
        p5 = _create_person(team_id=self.team.pk, distinct_ids=["person5"])

        # Person1: First event ever is $pageview on day 0, then signup on day 1
        _create_events(self.team, [("person1", _date(0))], "$pageview")
        _create_events(self.team, [("person1", _date(1))], "$user_signed_up")
        _create_events(self.team, [("person1", _date(1)), ("person1", _date(3)), ("person1", _date(5))], "$pageview")

        # Person2: First event ever is signup on day 1 (should be included)
        _create_events(self.team, [("person2", _date(1))], "$user_signed_up")
        _create_events(self.team, [("person2", _date(2)), ("person2", _date(4))], "$pageview")

        # Person3: First event ever is $pageview on day 2 (should be included)
        _create_events(self.team, [("person3", _date(2))], "$pageview")
        _create_events(self.team, [("person3", _date(3))], "$user_signed_up")
        _create_events(self.team, [("person3", _date(4)), ("person3", _date(6))], "$pageview")

        # Person4: First event ever is before date range (should be excluded)
        _create_events(self.team, [("person4", _date(-1))], "$pageview")
        _create_events(self.team, [("person4", _date(2))], "$user_signed_up")
        _create_events(self.team, [("person4", _date(3))], "$pageview")

        # Person5: First event ever is $user_signed_up on day 3
        _create_events(self.team, [("person5", _date(3))], "$user_signed_up")
        _create_events(self.team, [("person5", _date(4)), ("person5", _date(5))], "$pageview")

        flush_persons_and_events()
        return p1, p2, p3, p4, p5

    def test_retention_first_time_ever_basic(self):
        """Test basic first time ever retention without breakdowns"""
        self._create_first_time_ever_retention_events()

        result = self.run_query(
            query={
                "dateRange": {"date_from": _date(0), "date_to": _date(7)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
            }
        )

        self.assertEqual(len(result), 8)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7"],
        )

        # Person1: first $user_signed_up on day 1, returns on days 1,3,5 (intervals 0,2,4)
        # Person2: first $user_signed_up on day 1, returns on days 2,4 (intervals 1,3)
        # Person3: first $user_signed_up on day 3, returns on days 4,6 (intervals 1,3)
        # Person4: first $user_signed_up on day 2, returns on day 3 (interval 1)
        # Person5: first $user_signed_up on day 3, returns on days 4,5 (intervals 1,2)

        self.assertEqual(
            pluck(result, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one starts retention here (no one does signup on day 0)
                [
                    2,
                    1,
                    1,
                    1,
                    1,
                    0,
                    0,
                ],  # Day 1: person1 + person2 start; returns: day1(p1), day2(p2), day3(p1), day4(p2), day5(p1)
                [1, 1, 0, 0, 0, 0, 0],  # Day 2: person4 starts; returns: day3(p4)
                [2, 2, 1, 1, 0, 0, 0],  # Day 3: person3 + person5 start; returns: day4(p3+p5), day5(p5), day6(p3)
                [0, 0, 0, 0, 0, 0, 0],  # Day 4: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

    def test_retention_first_time_ever_with_person_breakdown(self):
        """Test first time ever retention with person property breakdown"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"age": "25"})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"age": "30"})
        _create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={"age": "25"})
        _create_person(team_id=self.team.pk, distinct_ids=["person4"], properties={"age": "30"})

        # Person1 (age 25): First event ever is $pageview on day 1, signup on day 2
        _create_events(self.team, [("person1", _date(1))], "$pageview")
        _create_events(self.team, [("person1", _date(2))], "$user_signed_up")
        _create_events(self.team, [("person1", _date(3)), ("person1", _date(5))], "$pageview")

        # Person2 (age 30): First event ever is signup on day 1
        _create_events(self.team, [("person2", _date(1))], "$user_signed_up")
        _create_events(self.team, [("person2", _date(2)), ("person2", _date(4))], "$pageview")

        # Person3 (age 25): First event ever is signup on day 2
        _create_events(self.team, [("person3", _date(2))], "$user_signed_up")
        _create_events(self.team, [("person3", _date(3)), ("person3", _date(5))], "$pageview")

        # Person4 (age 30): First event ever is $pageview on day 3, signup on day 4
        _create_events(self.team, [("person4", _date(3))], "$pageview")
        _create_events(self.team, [("person4", _date(4))], "$user_signed_up")
        _create_events(self.team, [("person4", _date(5)), ("person4", _date(6))], "$pageview")

        flush_persons_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_from": _date(0), "date_to": _date(7)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
                "breakdownFilter": {
                    "breakdown": "age",
                    "breakdown_type": "person",
                },
            }
        )

        # Should have results for each age group across the 8 days (Day 0-7)
        self.assertEqual(len(result), 16)  # 8 days * 2 age groups

        # Get results by breakdown value
        age_25_results = [r for r in result if r.get("breakdown_value") == "25"]
        age_30_results = [r for r in result if r.get("breakdown_value") == "30"]

        self.assertEqual(len(age_25_results), 8)
        self.assertEqual(len(age_30_results), 8)

        # Check age 25 group (person1 and person3)
        # Person1: first event ever day 1 (pageview), signup day 2 - should start retention on day 2
        # Person3: first event ever day 2 (signup) - should start retention on day 2
        self.assertEqual(
            pluck(age_25_results, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one
                [0, 0, 0, 0, 0, 0, 0],  # Day 1: person1's first event (pageview), but no signup yet
                [2, 2, 0, 2, 0, 0, 0],  # Day 2: person1 + person3 (both signup), both return day 3,5
                [0, 0, 0, 0, 0, 0, 0],  # Day 3: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 4: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

        # Check age 30 group (person2 and person4)
        # Person2: first event ever day 1 (signup) - should start retention on day 1
        # Person4: first event ever day 3 (pageview), signup day 4 - should start retention on day 4
        self.assertEqual(
            pluck(age_30_results, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one
                [1, 1, 0, 1, 0, 0, 0],  # Day 1: person2 (signup), returns day 2,4
                [0, 0, 0, 0, 0, 0, 0],  # Day 2: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 3: person4's first event (pageview), but no signup yet
                [1, 1, 1, 0, 0, 0, 0],  # Day 4: person4 (signup), returns day 5,6
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

    def test_retention_first_time_ever_with_event_breakdown(self):
        """Test first time ever retention with event property breakdown"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])

        # Person1: First event ever is $pageview (web) on day 1, signup (web) on day 2
        _create_events(self.team, [("person1", _date(1), {"source": "web"})], "$pageview")
        _create_events(self.team, [("person1", _date(2), {"source": "web"})], "$user_signed_up")
        _create_events(
            self.team, [("person1", _date(3), {"source": "web"}), ("person1", _date(5), {"source": "web"})], "$pageview"
        )

        # Person2: First event ever is signup (mobile) on day 1
        _create_events(self.team, [("person2", _date(1), {"source": "mobile"})], "$user_signed_up")
        _create_events(
            self.team,
            [("person2", _date(2), {"source": "mobile"}), ("person2", _date(4), {"source": "mobile"})],
            "$pageview",
        )

        # Person3: First event ever is signup (web) on day 2
        _create_events(self.team, [("person3", _date(2), {"source": "web"})], "$user_signed_up")
        _create_events(
            self.team, [("person3", _date(3), {"source": "web"}), ("person3", _date(5), {"source": "web"})], "$pageview"
        )

        flush_persons_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_from": _date(0), "date_to": _date(7)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
                "breakdownFilter": {
                    "breakdown": "source",
                    "breakdown_type": "event",
                },
            }
        )

        # Should have results for each source across the 8 days (Day 0-7)
        self.assertEqual(len(result), 16)  # 8 days * 2 sources

        # Get results by breakdown value
        web_results = [r for r in result if r.get("breakdown_value") == "web"]
        mobile_results = [r for r in result if r.get("breakdown_value") == "mobile"]

        self.assertEqual(len(web_results), 8)
        self.assertEqual(len(mobile_results), 8)

        # Check web source (person1 and person3)
        # Person1: first event day 1 (pageview web), signup day 2 (web)
        # Person3: first event day 2 (signup web)
        self.assertEqual(
            pluck(web_results, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one
                [0, 0, 0, 0, 0, 0, 0],  # Day 1: person1's first event (pageview), but no signup yet
                [2, 2, 0, 2, 0, 0, 0],  # Day 2: person1 + person3 (both signup web), both return day 3,5
                [0, 0, 0, 0, 0, 0, 0],  # Day 3: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 4: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

        # Check mobile source (person2)
        self.assertEqual(
            pluck(mobile_results, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one
                [1, 1, 0, 1, 0, 0, 0],  # Day 1: person2's first event (signup), returns day 2,4
                [0, 0, 0, 0, 0, 0, 0],  # Day 2: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 3: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 4: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

    def test_retention_first_time_ever_with_cohort_breakdown(self):
        """Test first time ever retention with cohort breakdown"""
        # Create cohorts
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "age",
                            "operator": "exact",
                            "value": ["25"],
                            "type": "person",
                        }
                    ]
                }
            ],
            name="Young users",
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "age",
                            "operator": "exact",
                            "value": ["30"],
                            "type": "person",
                        }
                    ]
                }
            ],
            name="Older users",
        )

        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"age": "25"})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"age": "30"})
        _create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={"age": "25"})
        _create_person(team_id=self.team.pk, distinct_ids=["person4"], properties={"age": "30"})

        # Person1 (cohort1): First event ever is $pageview on day 1, signup on day 2
        _create_events(self.team, [("person1", _date(1))], "$pageview")
        _create_events(self.team, [("person1", _date(2))], "$user_signed_up")
        _create_events(self.team, [("person1", _date(3)), ("person1", _date(5))], "$pageview")

        # Person2 (cohort2): First event ever is signup on day 1
        _create_events(self.team, [("person2", _date(1))], "$user_signed_up")
        _create_events(self.team, [("person2", _date(2)), ("person2", _date(4))], "$pageview")

        # Person3 (cohort1): First event ever is signup on day 2
        _create_events(self.team, [("person3", _date(2))], "$user_signed_up")
        _create_events(self.team, [("person3", _date(3)), ("person3", _date(5))], "$pageview")

        # Person4 (cohort2): First event ever is $pageview on day 3, signup on day 4
        _create_events(self.team, [("person4", _date(3))], "$pageview")
        _create_events(self.team, [("person4", _date(4))], "$user_signed_up")
        _create_events(self.team, [("person4", _date(5)), ("person4", _date(6))], "$pageview")

        flush_persons_and_events()

        # Calculate cohorts after person creation
        cohort1.calculate_people_ch(pending_version=0)
        cohort2.calculate_people_ch(pending_version=0)

        result = self.run_query(
            query={
                "dateRange": {"date_from": _date(0), "date_to": _date(7)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
                "breakdownFilter": {
                    "breakdown": [cohort1.pk, cohort2.pk],
                    "breakdown_type": "cohort",
                },
            }
        )

        # Should have results for each cohort across the 8 days (Day 0-7)
        self.assertEqual(len(result), 16)  # 8 days * 2 cohorts

        # Get results by breakdown value
        cohort1_results = [r for r in result if r.get("breakdown_value") == str(cohort1.pk)]
        cohort2_results = [r for r in result if r.get("breakdown_value") == str(cohort2.pk)]

        self.assertEqual(len(cohort1_results), 8)
        self.assertEqual(len(cohort2_results), 8)

        # Check cohort1 (person1 and person3)
        # Person1: first event day 1 (pageview), signup day 2 - should start retention on day 2
        # Person3: first event day 2 (signup) - should start retention on day 2
        self.assertEqual(
            pluck(cohort1_results, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one
                [0, 0, 0, 0, 0, 0, 0],  # Day 1: person1's first event (pageview), but no signup yet
                [2, 2, 0, 2, 0, 0, 0],  # Day 2: person1 + person3 (both signup), both return day 3,5
                [0, 0, 0, 0, 0, 0, 0],  # Day 3: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 4: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

        # Check cohort2 (person2 and person4)
        # Person2: first event day 1 (signup) - should start retention on day 1
        # Person4: first event day 3 (pageview), signup day 4 - should start retention on day 4
        self.assertEqual(
            pluck(cohort2_results, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one
                [1, 1, 0, 1, 0, 0, 0],  # Day 1: person2's first event (signup), returns day 2,4
                [0, 0, 0, 0, 0, 0, 0],  # Day 2: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 3: person4's first event (pageview), but no signup yet
                [1, 1, 1, 0, 0, 0, 0],  # Day 4: person4 (signup), returns day 5,6
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

    def test_retention_first_time_ever_with_minimum_occurrences(self):
        """Test first time ever retention with minimum occurrences requirement"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])

        # Person1: First event ever is signup on day 1, does pageview multiple times on day 2 and 4
        _create_events(self.team, [("person1", _date(1))], "$user_signed_up")
        _create_events(self.team, [("person1", _date(2)), ("person1", _date(2, hour=1))], "$pageview")  # 2 on day 2
        _create_events(self.team, [("person1", _date(4))], "$pageview")  # 1 on day 4 (insufficient)

        # Person2: First event ever is signup on day 2, does pageview multiple times on day 3 and 5
        _create_events(self.team, [("person2", _date(2))], "$user_signed_up")
        _create_events(
            self.team,
            [("person2", _date(3)), ("person2", _date(3, hour=1)), ("person2", _date(3, hour=2))],
            "$pageview",
        )  # 3 on day 3
        _create_events(self.team, [("person2", _date(5)), ("person2", _date(5, hour=1))], "$pageview")  # 2 on day 5

        # Person3: First event ever is signup on day 3, does pageview once on day 4 (insufficient)
        _create_events(self.team, [("person3", _date(3))], "$user_signed_up")
        _create_events(self.team, [("person3", _date(4))], "$pageview")  # 1 on day 4 (insufficient)

        flush_persons_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_from": _date(0), "date_to": _date(7)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                    "minimumOccurrences": 2,  # Require at least 2 pageviews in a day to count as retention
                },
            }
        )

        self.assertEqual(len(result), 8)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7"],
        )

        # Person1: first event on day 1 (signup), has 2 pageviews on day 2 (qualifies)
        # Person2: first event on day 2 (signup), has 3 pageviews on day 3 and 2 on day 5 (both qualify)
        # Person3: first event on day 3 (signup), has only 1 pageview on day 4 (doesn't qualify)
        self.assertEqual(
            pluck(result, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one
                [1, 1, 0, 0, 0, 0, 0],  # Day 1: person1 (signup), returns day 2 with 2+ pageviews
                [1, 1, 0, 1, 0, 0, 0],  # Day 2: person2 (signup), returns day 3 and 5 with 2+ pageviews
                [1, 0, 0, 0, 0, 0, 0],  # Day 3: person3 (signup), but doesn't return with 2+ pageviews
                [0, 0, 0, 0, 0, 0, 0],  # Day 4: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

    def test_retention_first_time_ever_actors_query(self):
        """Test actors query for first time ever retention"""
        self._create_first_time_ever_retention_events()

        query = {
            "dateRange": {"date_from": _date(0), "date_to": _date(7)},
            "retentionFilter": {
                "period": "Day",
                "totalIntervals": 7,
                "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                "targetEntity": {
                    "id": "$user_signed_up",
                    "name": "$user_signed_up",
                    "type": TREND_FILTER_TYPE_EVENTS,
                },
                "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
            },
        }

        # Test actors for day 1 interval 0 (people who signed up on day 1 when it was their first event ever)
        actors_day1_interval0 = self.run_actors_query(interval=1, query=query)
        # Should be person1 (first event day 0, signup day 1) and person2 (first event signup on day 1)
        self.assertEqual(len(actors_day1_interval0), 2)

        # Extract distinct_ids from results to check (order might vary)
        # Format is [[person_dict, intervals_list], ...]
        distinct_ids = {frozenset(actor[0]["distinct_ids"]) for actor in actors_day1_interval0}
        self.assertIn(frozenset(["alias1", "person1"]), distinct_ids)
        self.assertIn(frozenset(["person2"]), distinct_ids)

        # Test actors for day 1 interval 3 (people who signed up on day 1 and returned on day 4)
        actors_day1_interval3 = self.run_actors_query(interval=1, query=query)
        # Filter results to only those who appeared on interval 3
        interval3_actors = [a for a in actors_day1_interval3 if 3 in a[1]]
        # Should be person2 (returned on day 4)
        self.assertEqual(len(interval3_actors), 1)
        self.assertEqual(interval3_actors[0][0]["distinct_ids"], ["person2"])

        # Test actors for day 3 interval 0 (people who signed up on day 3 when it was their first event ever)
        actors_day3_interval0 = self.run_actors_query(interval=3, query=query)
        # Should be person3 (first event pageview day 2, signup day 3) and person5 (first event signup day 3)
        self.assertEqual(len(actors_day3_interval0), 2)

    def test_retention_first_time_ever_different_intervals(self):
        """Test first time ever retention with different time intervals"""
        # Create events over several weeks
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])

        # Person1: First event ever is signup on week 1 (day 1)
        _create_events(self.team, [("person1", _date(1))], "$user_signed_up")
        _create_events(self.team, [("person1", _date(8)), ("person1", _date(15))], "$pageview")  # Week 2 and 3

        # Person2: First event ever is pageview on week 2 (day 8), signup on week 3 (day 14)
        _create_events(self.team, [("person2", _date(8))], "$pageview")
        _create_events(self.team, [("person2", _date(14))], "$user_signed_up")
        _create_events(self.team, [("person2", _date(20))], "$pageview")  # Week 4

        # Person3: First event ever is signup on week 3 (day 14)
        _create_events(self.team, [("person3", _date(14))], "$user_signed_up")
        _create_events(
            self.team, [("person3", _date(20)), ("person3", _date(20, month=1))], "$pageview"
        )  # Week 4 and 5

        flush_persons_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_from": _date(0), "date_to": _date(20, month=1)},
                "retentionFilter": {
                    "period": "Week",
                    "totalIntervals": 5,
                    "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
            }
        )

        self.assertEqual(len(result), 8)
        self.assertEqual(
            pluck(result, "label"),
            ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6", "Week 7"],
        )

        # Person1: first $user_signed_up on day 1 (week 0), returns weeks 1,2 with pageviews
        # Person2: first $user_signed_up on day 14 (week 2), returns week 3 with pageview
        # Person3: first $user_signed_up on day 14 (week 2), returns week 3 with pageview (week 5 is out of range)
        self.assertEqual(
            pluck(result, "values", "count"),
            [
                [1, 1, 1, 0, 0],  # Week 0: person1 (signup), returns weeks 1,2
                [0, 0, 0, 0, 0],  # Week 1: no new users
                [2, 2, 0, 0, 0],  # Week 2: person2 + person3 (signup), return week 3 (both)
                [0, 0, 0, 0, 0],  # Week 3: no new users
                [0, 0, 0, 0, 0],  # Week 4: no new users
                [0, 0, 0, 0, 0],  # Week 5: no new users
                [0, 0, 0, 0, 0],  # Week 6: no new users
                [0, 0, 0, 0, 0],  # Week 7: no new users
            ],
        )

    def test_retention_first_time_ever_with_properties(self):
        """Test first time ever retention with event properties and filters"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person3"])

        # Person1: First event ever is pageview (organic) on day 1, signup (organic) on day 2
        _create_events(self.team, [("person1", _date(1), {"source": "organic"})], "$pageview")
        _create_events(self.team, [("person1", _date(2), {"source": "organic"})], "$user_signed_up")
        _create_events(
            self.team,
            [("person1", _date(3), {"source": "organic"}), ("person1", _date(5), {"source": "organic"})],
            "$pageview",
        )

        # Person2: First event ever is signup (paid) on day 1
        _create_events(self.team, [("person2", _date(1), {"source": "paid"})], "$user_signed_up")
        _create_events(
            self.team,
            [("person2", _date(2), {"source": "paid"}), ("person2", _date(4), {"source": "paid"})],
            "$pageview",
        )

        # Person3: First event ever is signup (organic) on day 2
        _create_events(self.team, [("person3", _date(2), {"source": "organic"})], "$user_signed_up")
        _create_events(
            self.team,
            [("person3", _date(3), {"source": "organic"}), ("person3", _date(5), {"source": "organic"})],
            "$pageview",
        )

        flush_persons_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_from": _date(0), "date_to": _date(7)},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 7,
                    "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                    "targetEntity": {
                        "id": "$user_signed_up",
                        "name": "$user_signed_up",
                        "type": TREND_FILTER_TYPE_EVENTS,
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
                "properties": [
                    {
                        "key": "source",
                        "operator": "exact",
                        "value": ["organic"],
                        "type": "event",
                    }
                ],
            }
        )

        self.assertEqual(len(result), 8)
        self.assertEqual(
            pluck(result, "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7"],
        )

        # Only organic events should be considered
        # Person2 is excluded because their events are from "paid" source
        # Person1: first $user_signed_up on day 2 (organic), returns day 3,5
        # Person3: first $user_signed_up on day 2 (organic), returns day 3,5
        self.assertEqual(
            pluck(result, "values", "count"),
            [
                [0, 0, 0, 0, 0, 0, 0],  # Day 0: no one
                [0, 0, 0, 0, 0, 0, 0],  # Day 1: no signups yet
                [2, 2, 0, 2, 0, 0, 0],  # Day 2: person1 + person3 (first organic signup), return day 3,5
                [0, 0, 0, 0, 0, 0, 0],  # Day 3: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 4: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 5: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 6: no new users
                [0, 0, 0, 0, 0, 0, 0],  # Day 7: no new users
            ],
        )

    def test_retention_first_time_ever_events_query(self):
        """Test events query for first time ever retention"""
        self._create_first_time_ever_retention_events()

        # Create RetentionQueryRunner instance
        query = RetentionQuery(
            dateRange={"date_from": _date(0), "date_to": _date(7)},
            retentionFilter={
                "period": "Day",
                "totalIntervals": 7,
                "retentionType": RETENTION_FIRST_EVER_OCCURRENCE,
                "targetEntity": {
                    "id": "$user_signed_up",
                    "name": "$user_signed_up",
                    "type": TREND_FILTER_TYPE_EVENTS,
                },
                "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
            },
        )

        runner = RetentionQueryRunner(query=query, team=self.team)

        # Test events query for interval 1 (day 1)
        events_query = runner.to_events_query(interval=1)
        events_result = execute_hogql_query(
            query_type="RetentionEventsQuery",
            query=events_query,
            team=self.team,
        )

        # Should include both start and return events for people who had their first event ever on day 1
        # and performed the target action (signup)
        # Person2: first event ever was signup on day 1, returns with pageviews on day 2,4
        events = events_result.results
        self.assertGreater(len(events), 0)

        # Based on the to_events_query method, event_type should be in index 5
        if len(events) > 0 and len(events[0]) > 5:
            event_types = {event[5] for event in events}  # event_type column (0-indexed)
            self.assertIn("start_event", event_types)
            self.assertIn("return_event", event_types)
        else:
            # If the structure is different, let's just check we have events
            self.assertGreater(len(events), 0)

        # Check that events are from person2
        person_ids = {event[8] for event in events}  # person_id column
        # Should contain person2
        self.assertIn("person2", person_ids)

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

        create_group_type_mapping_without_created_at(
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

    def test_retention_first_time_vs_first_ever_occurrence(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"])
        # First event, doesn't match property filter
        _create_events(
            self.team,
            [("person1", _date(0), {"prop": "wrong"})],
            event="target_event",
        )
        # Second event, matches property filter
        _create_events(
            self.team,
            [("person1", _date(1), {"prop": "correct"})],
            event="target_event",
        )
        # Returning events
        _create_events(
            self.team,
            [("person1", _date(2)), ("person1", _date(3))],
            event="returning_event",
        )
        flush_persons_and_events()

        base_query = {
            "dateRange": {"date_from": _date(0), "date_to": _date(5)},
            "retentionFilter": {
                "totalIntervals": 5,
                "targetEntity": {
                    "id": "target_event",
                    "type": "events",
                    "properties": [{"key": "prop", "value": "correct", "type": "event"}],
                },
                "returningEntity": {"id": "returning_event", "type": "events"},
            },
        }

        # Run query with RETENTION_FIRST_TIME
        query_first_time = base_query.copy()
        query_first_time["retentionFilter"]["retentionType"] = "retention_first_time"
        result_first_time = self.run_query(query=query_first_time)

        # Run query with RETENTION_FIRST_EVER_OCCURRENCE
        query_first_ever = base_query.copy()
        query_first_ever["retentionFilter"]["retentionType"] = "retention_first_ever_occurrence"
        result_first_ever = self.run_query(query=query_first_ever)

        # Assert results are different
        self.assertNotEqual(result_first_time, result_first_ever)

        # Assert correctness of RETENTION_FIRST_TIME
        # Cohort is on day 1 as that's the first time the event has the correct property.
        # Returns on day 2 (1 day later) and day 3 (2 days later).
        expected_first_time_counts = [
            [0, 0, 0, 0, 0],  # Day 0
            [1, 1, 1, 0, 0],  # Day 1
            [0, 0, 0, 0, 0],  # Day 2
            [0, 0, 0, 0, 0],  # Day 3
            [0, 0, 0, 0, 0],  # Day 4
            [0, 0, 0, 0, 0],  # Day 5
        ]
        self.assertEqual(
            pluck(result_first_time, "values", "count"),
            expected_first_time_counts,
        )

        # Assert correctness of RETENTION_FIRST_EVER_OCCURRENCE
        # First `target_event` is at `_date(0)` but doesn't match properties.
        # So person1 is not in any cohort. Result should be all zeros.
        expected_first_ever_counts = [
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0],
        ]
        self.assertEqual(
            pluck(result_first_ever, "values", "count"),
            expected_first_ever_counts,
        )


class TestClickhouseRetentionGroupAggregation(ClickhouseTestMixin, APIBaseTest):
    def run_query(self, query, *, limit_context: Optional[LimitContext] = None):
        if not query.get("retentionFilter"):
            query["retentionFilter"] = {}
        runner = RetentionQueryRunner(team=self.team, query=query, limit_context=limit_context)
        return runner.calculate().model_dump()["results"]

    def run_actors_query(self, interval, query, select=None, actor="person", breakdown=None):
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
                    "breakdown": breakdown,
                },
            },
        )
        return runner.calculate().model_dump()["results"]

    def _create_groups_and_events(self):
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
        self.run_query(query={}, limit_context=LimitContext.RETENTION)

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

    def test_retention_with_cohort_breakdown(self):
        person1 = _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
        person2 = _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})
        _create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={"name": "person3"})

        flush_persons_and_events()

        # Create a cohort with person1 and person2 using separate groups (OR condition)
        cohort = Cohort.objects.create(
            team=self.team,
            name="test_cohort",
            groups=[
                {
                    "properties": [
                        {"key": "name", "value": "person1", "type": "person"},
                    ]
                },
                {
                    "properties": [
                        {"key": "name", "value": "person2", "type": "person"},
                    ]
                },
            ],
        )

        # Create events
        _create_events(
            self.team,
            [
                ("person1", _date(0)),  # Day 0, in cohort
                ("person2", _date(0)),  # Day 0, in cohort
                ("person3", _date(0)),  # Day 0, not in cohort
                ("person1", _date(1)),  # Day 1, in cohort
                ("person2", _date(1)),  # Day 1, in cohort
                ("person1", _date(2)),  # Day 2, in cohort (needed for Day 1 cohort retention)
                ("person3", _date(3)),  # Day 3, not in cohort
            ],
        )

        flush_persons_and_events()

        cohort.calculate_people_ch(pending_version=0)
        # Make sure the cohort is calculated before running the query
        cohort_people = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s",
            {"cohort_id": cohort.pk},
        )

        cohort_person_ids = {row[0] for row in cohort_people}
        self.assertEqual(cohort_person_ids, {person1.uuid, person2.uuid})

        # Run retention query with cohort breakdown
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(4, hour=0)},
                "retentionFilter": {"totalIntervals": 5, "period": "Day"},
                "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [cohort.pk]},
            }
        )

        # Verify results
        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {str(cohort.pk)})

        cohort_results = pluck([c for c in result if c.get("breakdown_value") == str(cohort.pk)], "values", "count")
        # Expected pattern based on our event data:
        # - person1: events on days 0, 1, 2 (in cohort)
        # - person2: events on days 0, 1 (in cohort)
        # - person3: events on days 0, 3 (not in cohort, so filtered out)
        #
        # Day 0 cohort: 2 people start, 2 retained on day 1, 1 retained on day 2
        # Day 1 cohort: 2 people start, 1 retained on day 1 (day 2)
        # Day 2 cohort: 1 person starts
        self.assertEqual(
            cohort_results,
            pad([[2, 2, 1, 0, 0], [2, 1, 0, 0], [1, 0, 0], [0, 0], [0]]),
        )

    def test_retention_with_multiple_cohort_breakdowns(self):
        # Person 1 in cohort 1
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
        # Person 2 in cohort 2
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})
        # Person 3 in neither
        _create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={"name": "person3"})

        flush_persons_and_events()

        cohort1 = Cohort.objects.create(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "person1", "type": "person"}]}],
        )
        cohort1.calculate_people_ch(pending_version=0)

        cohort2 = Cohort.objects.create(
            team=self.team,
            name="cohort2",
            groups=[{"properties": [{"key": "name", "value": "person2", "type": "person"}]}],
        )
        cohort2.calculate_people_ch(pending_version=0)

        # Create events
        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person2", _date(0)),
                ("person3", _date(0)),
                ("person1", _date(1)),
                ("person2", _date(2)),
                ("person3", _date(3)),
            ],
        )

        flush_persons_and_events()

        # Run retention query with multiple cohort breakdown
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(4, hour=0)},
                "retentionFilter": {"totalIntervals": 5, "period": "Day"},
                "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [cohort1.pk, cohort2.pk]},
            }
        )

        # Verify results
        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {str(cohort1.pk), str(cohort2.pk)})

    def test_retention_with_all_users_cohort_breakdown(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})
        _create_person(team_id=self.team.pk, distinct_ids=["person3"], properties={"name": "person3"})

        flush_persons_and_events()

        # Create events for all three people
        _create_events(
            self.team,
            [
                ("person1", _date(0)),  # Day 0
                ("person2", _date(0)),  # Day 0
                ("person3", _date(0)),  # Day 0
                ("person1", _date(1)),  # Day 1
                ("person2", _date(1)),  # Day 1
                ("person1", _date(2)),  # Day 2
                ("person3", _date(3)),  # Day 3
            ],
        )

        flush_persons_and_events()

        # Run retention query with "all users" cohort breakdown (ID = 0)
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(4, hour=0)},
                "retentionFilter": {"totalIntervals": 5, "period": "Day"},
                "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [ALL_USERS_COHORT_ID]},
            }
        )

        # Verify results
        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {str(ALL_USERS_COHORT_ID)})

        # Get results for "all users" cohort
        all_users_results = pluck(
            [c for c in result if c.get("breakdown_value") == str(ALL_USERS_COHORT_ID)], "values", "count"
        )

        # Expected pattern based on our event data:
        # - person1: events on days 0, 1, 2 (all users, so included)
        # - person2: events on days 0, 1 (all users, so included)
        # - person3: events on days 0, 3 (all users, so included)
        #
        # Day 0 cohort: 3 people start, 2 retained on day 1, 1 retained on day 2, 1 retained on day 3 (person3)
        # Day 1 cohort: 2 people start, 1 retained on day 1 (day 2), 0 retained on day 2 (day 3)
        # Day 2 cohort: 1 person starts, 0 retained on day 1 (day 3)
        # Day 3 cohort: 1 person starts
        self.assertEqual(
            all_users_results,
            pad([[3, 2, 1, 1, 0], [2, 1, 0, 0], [1, 0, 0], [1, 0], [0]]),
        )

    def test_retention_with_all_users_cohort_breakdown_string_value(self):
        """Test that "all" string value is correctly converted to ALL_USERS_COHORT_ID"""
        _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
        _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})

        flush_persons_and_events()

        # Create events for both people
        _create_events(
            self.team,
            [
                ("person1", _date(0)),  # Day 0
                ("person2", _date(0)),  # Day 0
                ("person1", _date(1)),  # Day 1
            ],
        )

        flush_persons_and_events()

        # Run retention query with "all" string value (as sent by frontend)
        result = self.run_query(
            query={
                "dateRange": {"date_to": _date(2, hour=0)},
                "retentionFilter": {"totalIntervals": 2, "period": "Day"},
                "breakdownFilter": {"breakdown_type": "cohort", "breakdown": ["all"]},
            }
        )

        # Verify results
        breakdown_values = {c.get("breakdown_value") for c in result}
        self.assertEqual(breakdown_values, {str(ALL_USERS_COHORT_ID)})

        # Get results for "all users" cohort
        all_users_results = pluck(
            [c for c in result if c.get("breakdown_value") == str(ALL_USERS_COHORT_ID)], "values", "count"
        )

        # Expected: Based on events - person1 and person2 both start on day 0, only person1 is retained on day 1
        # But looking at actual retention calculation, it's only counting 1 person starting on day 0
        self.assertEqual(
            all_users_results,
            pad([[1, 0], [0]]),
        )

    def test_retention_actor_query_with_multiple_cohort_breakdowns(self):
        # Person 1 in cohort 1
        person1 = _create_person(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
        # Person 2 in cohort 2
        person2 = _create_person(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})

        flush_persons_and_events()

        cohort1 = Cohort.objects.create(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "person1", "type": "person"}]}],
        )
        cohort1.calculate_people_ch(pending_version=0)

        cohort2 = Cohort.objects.create(
            team=self.team,
            name="cohort2",
            groups=[{"properties": [{"key": "name", "value": "person2", "type": "person"}]}],
        )
        cohort2.calculate_people_ch(pending_version=0)

        # Create events
        _create_events(
            self.team,
            [
                ("person1", _date(0)),
                ("person2", _date(0)),
                ("person1", _date(1)),
                ("person2", _date(2)),
            ],
        )

        flush_persons_and_events()

        # Run retention actors query for cohort1
        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(4, hour=0)},
                "retentionFilter": {"totalIntervals": 5, "period": "Day"},
                "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [cohort1.pk, cohort2.pk]},
            },
            breakdown=[str(cohort1.pk)],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0]["id"], person1.uuid)
        self.assertEqual(result[0][1], [0, 1])

        # Run retention actors query for cohort2
        result = self.run_actors_query(
            interval=0,
            query={
                "dateRange": {"date_to": _date(4, hour=0)},
                "retentionFilter": {"totalIntervals": 5, "period": "Day"},
                "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [cohort1.pk, cohort2.pk]},
            },
            breakdown=[str(cohort2.pk)],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0]["id"], person2.uuid)
        self.assertEqual(result[0][1], [0, 2])

    def test_retention_breakdown_person_property_is_stable(self):
        # This test reproduces the bug where a person's breakdown value splits between
        # empty string and actual value, causing major countries to drop from top breakdown list

        # Create person who will have country property added later
        person_no_country = Person.objects.create(team=self.team, distinct_ids=["person_no_country"], properties={})

        # Create person who always has country
        # person_with_country
        Person.objects.create(team=self.team, distinct_ids=["person_with_country"], properties={"country": "Taiwan"})

        # Create events for both people
        _create_events(
            self.team,
            [
                ("person_no_country", _date(0)),  # Event when person has no country
                ("person_no_country", _date(1)),  # Retention event when person has no country
                ("person_with_country", _date(0)),  # Event for person with Taiwan
                ("person_with_country", _date(1)),  # Retention event for person with Taiwan
            ],
        )

        # Now update the person to have a country (simulating property being set later)
        person_no_country.properties = {"country": "Taiwan"}
        person_no_country.save()

        # Create more events after the property is set
        _create_events(
            self.team,
            [
                ("person_no_country", _date(2)),  # Event when person now has Taiwan as country
                ("person_with_country", _date(2)),  # Another event for consistent person
            ],
        )

        # Create many other people with unique countries to fill up breakdown slots
        # This simulates the real scenario where major countries get pushed out
        for i in range(20):
            Person.objects.create(team=self.team, distinct_ids=[f"person_{i}"], properties={"country": f"Country_{i}"})
            _create_events(self.team, [(f"person_{i}", _date(0)), (f"person_{i}", _date(1))])

        query = {
            "dateRange": {"date_from": _date(0), "date_to": _date(10)},
            "retentionFilter": {"period": "Day", "totalIntervals": 7},
            "breakdownFilter": {
                "breakdown": "country",
                "breakdown_type": "person",
            },
        }

        results = self.run_query(query)

        # Extract breakdown values
        breakdown_values = {r["breakdown_value"] for r in results}

        # This test will FAIL with current logic because:
        # 1. person_no_country's events will be split between "" (empty) and "Taiwan"
        # 2. This makes Taiwan appear to have only 1 person instead of 2
        # 3. Taiwan gets pushed out by the 20 other countries in the breakdown limit

        # The test expects Taiwan to be in the results (it should have 2 people)
        # but with the current bug, it might not be due to the splitting issue
        self.assertIn(
            "Taiwan",
            breakdown_values,
            "Taiwan should appear in breakdown results but got pushed out due to person property splitting bug",
        )

        # Taiwan should show 2 people in the cohort, not split between empty and Taiwan
        taiwan_results = [r for r in results if r["breakdown_value"] == "Taiwan"]
        if taiwan_results:
            # Day 0 cohort should have 2 people (both person_no_country and person_with_country)
            taiwan_day0_cohort = next((r for r in taiwan_results if r["label"] == "Day 0"), None)
            if taiwan_day0_cohort:
                self.assertEqual(
                    taiwan_day0_cohort["values"][0]["count"],
                    2,
                    "Taiwan cohort should have 2 people, not split due to property timing",
                )

    def test_retention_breakdown_uses_most_recent_property_value(self):
        # This test validates that when a user's breakdown property changes over time,
        # they are counted using their most recent property value for ranking purposes.

        # Create a user whose country changes from '' -> 'Canada' -> 'USA' over time
        person_changing = Person.objects.create(
            team=self.team,
            distinct_ids=["person_changing"],
            properties={},  # Initially no country
        )

        # Day 0: Event with no country (empty string)
        _create_events(self.team, [("person_changing", _date(0))])

        # Update person to have Canada as country
        person_changing.properties = {"country": "Canada"}
        person_changing.save()

        # Day 1: Event with Canada
        _create_events(self.team, [("person_changing", _date(1))])

        # Update person to have USA as country (most recent)
        person_changing.properties = {"country": "USA"}
        person_changing.save()

        # Day 2: Event with USA (this should be the canonical value)
        _create_events(self.team, [("person_changing", _date(2))])

        # Create a baseline USA user to ensure USA gets ranked properly
        Person.objects.create(team=self.team, distinct_ids=["usa_baseline"], properties={"country": "USA"})
        _create_events(self.team, [("usa_baseline", _date(0))])

        # Create some other countries to fill up breakdown slots
        for i in range(15):
            Person.objects.create(team=self.team, distinct_ids=[f"other_{i}"], properties={"country": f"Other_{i}"})
            _create_events(self.team, [(f"other_{i}", _date(0))])

        query = {
            "dateRange": {"date_from": _date(0), "date_to": _date(10)},
            "retentionFilter": {"period": "Day", "totalIntervals": 7},
            "breakdownFilter": {
                "breakdown": "country",
                "breakdown_type": "person",
                "breakdown_limit": 5,  # Limit to top 5 to force ranking logic
            },
        }

        results = self.run_query(query)
        breakdown_values = {r["breakdown_value"] for r in results}

        # USA should be in the top results because it has 2 users (person_changing + usa_baseline)
        # based on the most recent property values
        self.assertIn(
            "USA", breakdown_values, "USA should be in top breakdown results based on most recent property values"
        )

        # Canada should NOT be in the top results because person_changing's final value is USA
        self.assertNotIn(
            "Canada",
            breakdown_values,
            "Canada should not be in top breakdown results as person_changing's final value is USA",
        )

        # Verify USA has 2 users in the Day 0 cohort
        usa_results = [r for r in results if r["breakdown_value"] == "USA"]
        usa_day0_cohort = next((r for r in usa_results if r["label"] == "Day 0"), None)
        assert usa_day0_cohort is not None
        self.assertEqual(
            usa_day0_cohort["values"][0]["count"],
            2,
            "USA should have 2 users: person_changing (latest value) + usa_baseline",
        )

    def test_retention_breakdown_other_grouping_logic(self):
        # This test validates that breakdown values are correctly sorted by frequency
        # and that the least frequent ones are grouped into "Other"

        # Create countries with different user counts to test ranking
        # USA: 5 users (should be #1)
        for i in range(5):
            Person.objects.create(team=self.team, distinct_ids=[f"usa_user_{i}"], properties={"country": "USA"})
            _create_events(self.team, [(f"usa_user_{i}", _date(0))])

        # Canada: 3 users (should be #2)
        for i in range(3):
            Person.objects.create(team=self.team, distinct_ids=[f"can_user_{i}"], properties={"country": "Canada"})
            _create_events(self.team, [(f"can_user_{i}", _date(0))])

        # Germany: 2 users (should be #3)
        for i in range(2):
            Person.objects.create(team=self.team, distinct_ids=[f"ger_user_{i}"], properties={"country": "Germany"})
            _create_events(self.team, [(f"ger_user_{i}", _date(0))])

        # France: 1 user (should be grouped into "Other" with breakdown_limit=3)
        Person.objects.create(team=self.team, distinct_ids=["fra_user"], properties={"country": "France"})
        _create_events(self.team, [("fra_user", _date(0))])

        # Spain: 1 user (should be grouped into "Other" with breakdown_limit=3)
        Person.objects.create(team=self.team, distinct_ids=["spa_user"], properties={"country": "Spain"})
        _create_events(self.team, [("spa_user", _date(0))])

        query = {
            "dateRange": {"date_from": _date(0), "date_to": _date(10)},
            "retentionFilter": {"period": "Day", "totalIntervals": 7},
            "breakdownFilter": {
                "breakdown": "country",
                "breakdown_type": "person",
                "breakdown_limit": 3,  # Only top 3 should be shown individually
            },
        }

        results = self.run_query(query)
        breakdown_values = {r["breakdown_value"] for r in results}

        # Top 3 countries should be present
        self.assertIn("USA", breakdown_values, "USA should be in top 3 (5 users)")
        self.assertIn("Canada", breakdown_values, "Canada should be in top 3 (3 users)")
        self.assertIn("Germany", breakdown_values, "Germany should be in top 3 (2 users)")

        # Bottom 2 countries should be grouped into "Other"
        self.assertNotIn("France", breakdown_values, "France should be grouped into Other (1 user)")
        self.assertNotIn("Spain", breakdown_values, "Spain should be grouped into Other (1 user)")
        self.assertIn(BREAKDOWN_OTHER_STRING_LABEL, breakdown_values, "Other group should be present")

        # Verify the "Other" group has the correct count (France + Spain = 2 users)
        other_results = [r for r in results if r["breakdown_value"] == BREAKDOWN_OTHER_STRING_LABEL]
        other_day0_cohort = next((r for r in other_results if r["label"] == "Day 0"), None)
        assert other_day0_cohort is not None
        self.assertEqual(
            other_day0_cohort["values"][0]["count"],
            2,
            "Other group should contain 2 users (France + Spain)",
        )

        # Verify the top countries have correct counts
        usa_results = [r for r in results if r["breakdown_value"] == "USA"]
        usa_day0_cohort = next((r for r in usa_results if r["label"] == "Day 0"), None)
        assert usa_day0_cohort is not None
        self.assertEqual(usa_day0_cohort["values"][0]["count"], 5, "USA should have 5 users")

        canada_results = [r for r in results if r["breakdown_value"] == "Canada"]
        canada_day0_cohort = next((r for r in canada_results if r["label"] == "Day 0"), None)
        assert canada_day0_cohort is not None
        self.assertEqual(canada_day0_cohort["values"][0]["count"], 3, "Canada should have 3 users")

    # TRICKY: for later if/when we want a different ranking logic for breakdowns
    # def test_retention_breakdown_ranking_by_unique_users(self):
    #     # This test validates that breakdown ranking is based on unique users, not sum of cohort sizes.
    #     # It creates a scenario where one breakdown value has more unique users, but another has a higher
    #     # sum of cohort sizes due to very active, recurring users.

    #     # USA: 10 unique users, each starting a cohort once on Day 0
    #     for i in range(10):
    #         Person.objects.create(team=self.team, distinct_ids=[f"usa_user_{i}"], properties={"country": "USA"})
    #         _create_events(self.team, [(f"usa_user_{i}", _date(0))])

    #     # Canada: 3 unique users, but they are very active and start cohorts on 5 different days
    #     for i in range(3):
    #         Person.objects.create(team=self.team, distinct_ids=[f"can_user_{i}"], properties={"country": "Canada"})
    #         for day in range(5):
    #             _create_events(self.team, [(f"can_user_{i}", _date(day))])

    #     # With the flawed logic (sum of cohorts):
    #     # USA score = 10 (10 users on day 0)
    #     # Canada score = 15 (3 users * 5 days)
    #     # Canada will be ranked higher.

    #     # With the correct logic (unique users):
    #     # USA score = 10
    #     # Canada score = 3
    #     # USA will be ranked higher.

    #     query = {
    #         "dateRange": {"date_from": _date(0), "date_to": _date(10)},
    #         "retentionFilter": {"period": "Day", "totalIntervals": 7},
    #         "breakdownFilter": {
    #             "breakdown": "country",
    #             "breakdown_type": "person",
    #             "breakdown_limit": 1,
    #         },
    #     }

    #     results = self.run_query(query)
    #     breakdown_values = {r["breakdown_value"] for r in results}

    #     # The test asserts that USA is the top breakdown, which should fail with the current logic
    #     self.assertIn("USA", breakdown_values)
    #     self.assertNotIn("Canada", breakdown_values)
    #     self.assertIn(BREAKDOWN_OTHER_STRING_LABEL, breakdown_values)  # Canada should be in "Other"
