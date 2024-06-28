import json
import uuid
from datetime import datetime

from zoneinfo import ZoneInfo
from django.test import override_settings
from rest_framework import status

from posthog.constants import (
    FILTER_TEST_ACCOUNTS,
    RETENTION_FIRST_TIME,
    RETENTION_TYPE,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models import Action
from posthog.models.filters import RetentionFilter
from posthog.models.instance_setting import override_instance_config
from posthog.queries.retention.retention import Retention
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    snapshot_clickhouse_queries,
)


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


def retention_test_factory(retention):
    class TestRetention(ClickhouseTestMixin, APIBaseTest):
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

            result = retention().run(RetentionFilter(data={"dummy": "dummy"}), self.team)
            self.assertEqual(
                pluck(result, "values", "count"),
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
                ],
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
            result = retention().run(RetentionFilter(data={"date_to": _date(10, hour=6)}), self.team)
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
                ],
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

            filter = RetentionFilter(data={"date_to": _date(0, month=5, hour=0), "period": "Month"})

            result = retention().run(filter, self.team, total_intervals=11)

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
                ],
            )

            self.assertEqual(
                pluck(result, "date"),
                [
                    datetime(2020, 1, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 2, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 3, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 4, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 5, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 7, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 8, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 9, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 10, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 11, 10, 0, tzinfo=ZoneInfo("UTC")),
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

            filter = RetentionFilter(data={"date_to": _date(0, month=5, hour=0), "period": "Month"})

            result = retention().run(filter, self.team, total_intervals=11)

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
                ],
            )

            self.assertEqual(
                pluck(result, "date"),
                [
                    datetime(2020, 1, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 2, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 3, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 4, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 5, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 7, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 8, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 9, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 10, 10, 0, tzinfo=ZoneInfo("UTC")),
                    datetime(2020, 11, 10, 0, tzinfo=ZoneInfo("UTC")),
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

            test_filter = RetentionFilter(
                data={
                    "date_to": _date(10, month=1, hour=0),
                    "period": "Week",
                    "total_intervals": 7,
                }
            )

            # Starting with Sunday
            result_sunday = retention().run(
                test_filter,
                self.team,
            )

            self.assertEqual(
                pluck(result_sunday, "label"),
                ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
            )

            self.assertEqual(
                pluck(result_sunday, "values", "count"),
                [
                    [2, 2, 1, 2, 2, 0, 1],
                    [2, 1, 2, 2, 0, 1],
                    [1, 1, 1, 0, 0],
                    [2, 2, 0, 1],
                    [2, 0, 1],
                    [0, 0],
                    [1],
                ],
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

            result_monday = retention().run(
                test_filter,
                self.team,
            )

            self.assertEqual(
                pluck(result_monday, "label"),
                ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
            )

            self.assertEqual(
                pluck(result_monday, "values", "count"),
                [
                    [2, 2, 1, 2, 2, 0, 1],
                    [2, 1, 2, 2, 0, 1],
                    [1, 1, 1, 0, 0],
                    [2, 2, 0, 1],
                    [2, 0, 1],
                    [0, 0],
                    [1],
                ],
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

            filter = RetentionFilter(data={"date_to": _date(0, hour=16, minute=13), "period": "Hour"})

            result = retention().run(filter, self.team, total_intervals=11)

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
                ],
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

        # ensure that the first interval is properly rounded acoording to the specified period
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

            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": _date(14, month=1, hour=0),
                        "period": "Week",
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(
                pluck(result, "label"),
                ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
            )

            self.assertEqual(
                pluck(result, "values", "count"),
                [
                    [2, 2, 1, 2, 2, 0, 1],
                    [2, 1, 2, 2, 0, 1],
                    [1, 1, 1, 0, 0],
                    [2, 2, 0, 1],
                    [2, 0, 1],
                    [0, 0],
                    [1],
                ],
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
            result, _ = retention().actors_in_period(
                RetentionFilter(
                    data={"date_to": _date(10, hour=6), "selected_interval": 0},
                    team=self.team,
                ),
                self.team,
            )
            self.assertEqual(len(result), 1)
            self.assertTrue(result[0]["person"]["id"] == person1.uuid, person1.uuid)

        def test_retention_people_first_time(self):
            _, _, p3, _ = self._create_first_time_retention_events()
            # even if set to hour 6 it should default to beginning of day and include all pageviews above

            target_entity = json.dumps({"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS})
            result, _ = retention().actors_in_period(
                RetentionFilter(
                    data={
                        "date_to": _date(10, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "selected_interval": 0,
                    },
                    team=self.team,
                ),
                self.team,
            )

            self.assertEqual(len(result), 1)
            self.assertIn(result[0]["person"]["id"], [p3.uuid, p3.pk])

            result, _ = retention().actors_in_period(
                RetentionFilter(
                    data={
                        "date_to": _date(14, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "selected_interval": 0,
                    },
                    team=self.team,
                ),
                self.team,
            )

            self.assertEqual(len(result), 0)

        def test_retention_people_paginated(self):
            for i in range(150):
                person_id = "person{}".format(i)
                _create_person(team_id=self.team.pk, distinct_ids=[person_id])
                _create_events(
                    self.team,
                    [
                        (person_id, _date(0)),
                        (person_id, _date(1)),
                        (person_id, _date(2)),
                        (person_id, _date(5)),
                    ],
                )

            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = self.client.get(
                "/api/person/retention",
                data={"date_to": _date(10, hour=6), "selected_interval": 2},
            ).json()

            self.assertEqual(len(result["result"]), 100)

            second_result = self.client.get(result["next"]).json()
            self.assertEqual(len(second_result["result"]), 50)

        def test_retention_invalid_properties(self):
            response = self.client.get("/api/person/retention", data={"properties": "invalid_json"})

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertDictEqual(
                response.json(),
                self.validation_error_response("Properties are unparsable!", "invalid_input"),
            )

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
            result, _ = retention().actors_in_period(
                RetentionFilter(
                    data={"date_to": _date(10, hour=6), "selected_interval": 2},
                    team=self.team,
                ),
                self.team,
            )

            # should be descending order on number of appearances
            self.assertIn(result[0]["person"]["id"], [person2.pk, person2.uuid])
            self.assertEqual(result[0]["appearances"], [1, 1, 0, 0, 1, 1, 0, 0, 0])

            self.assertIn(result[1]["person"]["id"], [person1.pk, person1.uuid])
            self.assertEqual(result[1]["appearances"], [1, 0, 0, 1, 1, 0, 0, 0, 0])

        def test_retention_people_in_perieod_first_time(self):
            p1, p2, p3, p4 = self._create_first_time_retention_events()
            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            target_entity = json.dumps({"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS})
            result1, _ = retention().actors_in_period(
                RetentionFilter(
                    data={
                        "date_to": _date(10, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "selected_interval": 0,
                    },
                    team=self.team,
                ),
                self.team,
            )

            self.assertEqual(len(result1), 1)
            self.assertTrue(result1[0]["person"]["id"] == p3.pk or result1[0]["person"]["id"] == p3.uuid)
            self.assertEqual(result1[0]["appearances"], [1, 1, 0, 1, 1, 1, 0, 0, 0, 0, 0])

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

            target_entity = json.dumps({"id": first_event, "type": TREND_FILTER_TYPE_EVENTS})
            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": _date(6, hour=6),
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )
            self.assertEqual(len(result), 7)
            self.assertEqual(
                pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )

            self.assertEqual(
                pluck(result, "values", "count"),
                [
                    [2, 0, 0, 0, 0, 2, 1],
                    [2, 0, 0, 0, 2, 1],
                    [2, 0, 0, 2, 1],
                    [2, 0, 2, 1],
                    [0, 0, 0],
                    [1, 0],
                    [0],
                ],
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

            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": _date(6, hour=6),
                        "target_entity": json.dumps({"id": None, "type": "events"}),
                        "returning_entity": {"id": None, "type": "events"},
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )
            self.assertEqual(len(result), 7)
            self.assertEqual(
                pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )

            self.assertEqual(
                pluck(result, "values", "count"),
                [
                    [2, 2, 2, 2, 0, 2, 1],
                    [2, 2, 2, 0, 2, 1],
                    [2, 2, 0, 2, 1],
                    [2, 0, 2, 1],
                    [0, 0, 0],
                    [3, 1],
                    [1],
                ],
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

            start_entity = json.dumps({"id": action.pk, "type": TREND_FILTER_TYPE_ACTIONS})
            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": _date(6, hour=0),
                        "target_entity": start_entity,
                        "returning_entity": {
                            "id": some_event,
                            "type": TREND_FILTER_TYPE_EVENTS,
                        },
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 7)
            self.assertEqual(
                pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

            self.assertEqual(
                pluck(result, "values", "count"),
                [
                    [2, 0, 0, 1, 0, 1, 0],
                    [2, 0, 1, 0, 1, 0],
                    [2, 1, 0, 1, 0],
                    [2, 0, 1, 0],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ],
            )

        def test_first_time_retention(self):
            self._create_first_time_retention_events()

            target_entity = json.dumps({"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS})
            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": _date(5, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 7)
            self.assertEqual(
                pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )

            self.assertEqual(
                pluck(result, "values", "count"),
                [
                    [2, 1, 2, 2, 1, 0, 1],
                    [1, 1, 0, 1, 1, 1],
                    [0, 0, 0, 0, 0],
                    [1, 1, 0, 1],
                    [0, 0, 0],
                    [0, 0],
                    [0],
                ],
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

            result = retention().run(
                RetentionFilter(
                    data={
                        "properties": [{"key": "$some_property", "value": "value"}],
                        "date_to": _date(10, hour=0),
                    }
                ),
                self.team,
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
                ],
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

            result = retention().run(
                RetentionFilter(
                    data={
                        "properties": [
                            {
                                "key": "email",
                                "value": "person1@test.com",
                                "type": "person",
                            }
                        ],
                        "date_to": _date(6, hour=0),
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 7)
            self.assertEqual(
                pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))
            self.assertEqual(
                pluck(result, "values", "count"),
                [
                    [1, 1, 1, 0, 0, 1, 1],
                    [1, 1, 0, 0, 1, 1],
                    [1, 0, 0, 1, 1],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [1, 1],
                    [1],
                ],
            )

        @snapshot_clickhouse_queries
        def test_retention_with_user_properties_via_action(self):
            action = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$pageview",
                        "properties": [{"key": "email", "value": "person1@test.com", "type": "person"}],
                    }
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

            result = retention().run(
                RetentionFilter(
                    data={
                        "target_entity": json.dumps({"id": action.pk, "type": TREND_FILTER_TYPE_ACTIONS}),
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "date_to": _date(6, hour=0),
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 7)
            self.assertEqual(
                pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))
            self.assertEqual(
                pluck(result, "values", "count"),
                [
                    [1, 1, 1, 0, 0, 1, 1],
                    [1, 1, 0, 0, 1, 1],
                    [1, 0, 0, 1, 1],
                    [0, 0, 0, 0],
                    [0, 0, 0],
                    [1, 1],
                    [1],
                ],
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

            start_entity = json.dumps({"id": action.pk, "type": TREND_FILTER_TYPE_ACTIONS})
            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": _date(6, hour=0),
                        "target_entity": start_entity,
                        "actions": [{"id": action.pk, "type": TREND_FILTER_TYPE_ACTIONS}],
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 7)
            self.assertEqual(
                pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=ZoneInfo("UTC")))

            self.assertEqual(
                pluck(result, "values", "count"),
                [
                    [1, 1, 1, 0, 0, 1, 1],
                    [2, 2, 1, 0, 1, 2],
                    [2, 1, 0, 1, 2],
                    [1, 0, 0, 1],
                    [0, 0, 0],
                    [1, 1],
                    [2],
                ],
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

            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = retention().run(
                RetentionFilter(
                    data={"date_to": _date(10, hour=6), FILTER_TEST_ACCOUNTS: True},
                    team=self.team,
                ),
                self.team,
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
                ],
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

        def test_retention_aggregate_by_distinct_id(self):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=["person1", "alias1"],
                properties={"test": "ok"},
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

            with override_instance_config("AGGREGATE_BY_DISTINCT_IDS_TEAMS", f"{self.team.pk}"):
                # even if set to hour 6 it should default to beginning of day and include all pageviews above
                result = retention().run(RetentionFilter(data={"date_to": _date(10, hour=6)}), self.team)
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
                    [
                        [1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0],
                        [2, 2, 1, 0, 1, 2, 0, 0, 0, 0],
                        [2, 1, 0, 1, 2, 0, 0, 0, 0],
                        [1, 0, 0, 1, 0, 0, 0, 0],
                        [0, 0, 0, 0, 0, 0, 0],
                        [
                            2,
                            1,
                            0,
                            0,
                            0,
                            0,
                        ],  # this first day is different b/c of the distinct_id aggregation
                        [2, 0, 0, 0, 0],
                        [0, 0, 0, 0],
                        [0, 0, 0],
                        [0, 0],
                        [0],
                    ],
                )

                result = retention().run(
                    RetentionFilter(
                        data={
                            "date_to": _date(10, hour=6),
                            "properties": [{"key": "test", "value": "ok", "type": "person"}],
                        }
                    ),
                    self.team,
                )
                self.assertEqual(
                    pluck(result, "values", "count"),
                    [
                        [1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0],
                        [1, 1, 0, 0, 1, 1, 0, 0, 0, 0],
                        [1, 0, 0, 1, 1, 0, 0, 0, 0],
                        [0, 0, 0, 0, 0, 0, 0, 0],
                        [0, 0, 0, 0, 0, 0, 0],
                        [
                            2,
                            1,
                            0,
                            0,
                            0,
                            0,
                        ],  # this first day is different b/c of the distinct_id aggregation
                        [1, 0, 0, 0, 0],
                        [0, 0, 0, 0],
                        [0, 0, 0],
                        [0, 0],
                        [0],
                    ],
                )

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

            result = retention().run(
                RetentionFilter(data={"date_to": _date(10)}, team=self.team),
                self.team,
            )

            self.team.timezone = "US/Pacific"
            self.team.save()
            result_pacific = retention().run(
                RetentionFilter(data={"date_to": _date(10)}, team=self.team),
                self.team,
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
                ],
            )

            self.assertEqual(
                pluck(result_pacific, "values", "count"),
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
                ],
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
            result = retention().run(
                RetentionFilter(data={"date_to": _date(10, hour=6), "sampling_factor": 1}),
                self.team,
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
                ],
            )

    return TestRetention


class TestFOSSRetention(retention_test_factory(Retention)):  # type: ignore
    pass
