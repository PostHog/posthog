import json
from datetime import datetime

import pytz
from rest_framework import status

from posthog.constants import (
    FILTER_TEST_ACCOUNTS,
    RETENTION_FIRST_TIME,
    RETENTION_TYPE,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_LINEAR,
)
from posthog.models import Action, ActionStep, Event, Person
from posthog.models.filters import RetentionFilter
from posthog.queries.abstract_test.test_interval import AbstractIntervalTest
from posthog.queries.retention import Retention
from posthog.test.base import APIBaseTest


# parameterize tests to reuse in EE
def retention_test_factory(retention, event_factory, person_factory, action_factory):
    class TestRetention(AbstractIntervalTest, APIBaseTest):
        def test_retention_default(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            person_factory(team_id=self.team.pk, distinct_ids=["person2"])

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )

            result = retention().run(RetentionFilter(data={"dummy": "dummy"}), self.team)
            self.assertEqual(
                self.pluck(result, "values", "count"),
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
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )

            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = retention().run(RetentionFilter(data={"date_to": self._date(10, hour=6)}), self.team)
            self.assertEqual(len(result), 11)
            self.assertEqual(
                self.pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7", "Day 8", "Day 9", "Day 10",],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=pytz.UTC))

            self.assertEqual(
                self.pluck(result, "values", "count"),
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
            Person.objects.create(
                team=self.team, distinct_ids=["person1", "alias1"], properties={"email": "person1@test.com"},
            )
            Person.objects.create(
                team=self.team, distinct_ids=["person2"], properties={"email": "person2@test.com"},
            )

            self._create_events(
                [
                    ("person1", self._date(day=0, month=-5)),
                    ("person2", self._date(day=0, month=-5)),
                    ("person1", self._date(day=0, month=-4)),
                    ("person2", self._date(day=0, month=-4)),
                    ("person1", self._date(day=0, month=-3)),
                    ("person2", self._date(day=0, month=-3)),
                    ("person1", self._date(day=0, month=-1)),
                    ("person1", self._date(day=0, month=0)),
                    ("person2", self._date(day=0, month=0)),
                    ("person2", self._date(day=0, month=1)),
                    ("person1", self._date(day=0, month=3)),
                    ("person2", self._date(day=0, month=5)),
                ]
            )

            filter = RetentionFilter(data={"date_to": self._date(0, month=5, hour=0), "period": "Month"})

            result = retention().run(filter, self.team, total_intervals=11)

            self.assertEqual(
                self.pluck(result, "label"),
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
                self.pluck(result, "values", "count"),
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
                self.pluck(result, "date"),
                [
                    datetime(2020, 1, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 2, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 3, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 4, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 5, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 7, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 8, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 9, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 10, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 11, 10, 0, tzinfo=pytz.UTC),
                ],
            )

        def test_week_interval(self):
            Person.objects.create(
                team=self.team, distinct_ids=["person1", "alias1"], properties={"email": "person1@test.com"},
            )
            Person.objects.create(
                team=self.team, distinct_ids=["person2"], properties={"email": "person2@test.com"},
            )

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person2", self._date(0)),
                    ("person1", self._date(1)),
                    ("person2", self._date(1)),
                    ("person1", self._date(7)),
                    ("person2", self._date(7)),
                    ("person1", self._date(14)),
                    ("person1", self._date(month=1, day=-6)),
                    ("person2", self._date(month=1, day=-6)),
                    ("person2", self._date(month=1, day=1)),
                    ("person1", self._date(month=1, day=1)),
                    ("person2", self._date(month=1, day=15)),
                ]
            )

            result = retention().run(
                RetentionFilter(
                    data={"date_to": self._date(10, month=1, hour=0), "period": "Week", "total_intervals": 7}
                ),
                self.team,
            )

            self.assertEqual(
                self.pluck(result, "label"), ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
            )

            self.assertEqual(
                self.pluck(result, "values", "count"),
                [[2, 2, 1, 2, 2, 0, 1], [2, 1, 2, 2, 0, 1], [1, 1, 1, 0, 0], [2, 2, 0, 1], [2, 0, 1], [0, 0], [1],],
            )

            self.assertEqual(
                self.pluck(result, "date"),
                [
                    datetime(2020, 6, 7, 0, tzinfo=pytz.UTC),
                    datetime(2020, 6, 14, 0, tzinfo=pytz.UTC),
                    datetime(2020, 6, 21, 0, tzinfo=pytz.UTC),
                    datetime(2020, 6, 28, 0, tzinfo=pytz.UTC),
                    datetime(2020, 7, 5, 0, tzinfo=pytz.UTC),
                    datetime(2020, 7, 12, 0, tzinfo=pytz.UTC),
                    datetime(2020, 7, 19, 0, tzinfo=pytz.UTC),
                ],
            )

        def test_hour_interval(self):
            Person.objects.create(
                team=self.team, distinct_ids=["person1", "alias1"], properties={"email": "person1@test.com"},
            )
            Person.objects.create(
                team=self.team, distinct_ids=["person2"], properties={"email": "person2@test.com"},
            )

            self._create_events(
                [
                    ("person1", self._date(day=0, hour=6)),
                    ("person2", self._date(day=0, hour=6)),
                    ("person1", self._date(day=0, hour=7)),
                    ("person2", self._date(day=0, hour=7)),
                    ("person1", self._date(day=0, hour=8)),
                    ("person2", self._date(day=0, hour=8)),
                    ("person1", self._date(day=0, hour=10)),
                    ("person1", self._date(day=0, hour=11)),
                    ("person2", self._date(day=0, hour=11)),
                    ("person2", self._date(day=0, hour=12)),
                    ("person1", self._date(day=0, hour=14)),
                    ("person2", self._date(day=0, hour=16)),
                ]
            )

            filter = RetentionFilter(data={"date_to": self._date(0, hour=16), "period": "Hour"})

            result = retention().run(filter, self.team, total_intervals=11)

            self.assertEqual(
                self.pluck(result, "label"),
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
                self.pluck(result, "values", "count"),
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
                self.pluck(result, "date"),
                [
                    datetime(2020, 6, 10, 6, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 7, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 8, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 9, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 10, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 11, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 12, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 13, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 14, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 15, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 16, tzinfo=pytz.UTC),
                ],
            )

        # retention doesn't support minute
        def test_minute_interval(self):
            pass

        # ensure that the first interval is properly rounded acoording to the specified period
        def test_interval_rounding(self):
            Person.objects.create(
                team=self.team, distinct_ids=["person1", "alias1"], properties={"email": "person1@test.com"},
            )
            Person.objects.create(
                team=self.team, distinct_ids=["person2"], properties={"email": "person2@test.com"},
            )

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person2", self._date(0)),
                    ("person1", self._date(1)),
                    ("person2", self._date(1)),
                    ("person1", self._date(7)),
                    ("person2", self._date(7)),
                    ("person1", self._date(14)),
                    ("person1", self._date(month=1, day=-6)),
                    ("person2", self._date(month=1, day=-6)),
                    ("person2", self._date(month=1, day=1)),
                    ("person1", self._date(month=1, day=1)),
                    ("person2", self._date(month=1, day=15)),
                ]
            )

            result = retention().run(
                RetentionFilter(
                    data={"date_to": self._date(14, month=1, hour=0), "period": "Week", "total_intervals": 7}
                ),
                self.team,
            )

            self.assertEqual(
                self.pluck(result, "label"), ["Week 0", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
            )

            self.assertEqual(
                self.pluck(result, "values", "count"),
                [[2, 2, 1, 2, 2, 0, 1], [2, 1, 2, 2, 0, 1], [1, 1, 1, 0, 0], [2, 2, 0, 1], [2, 0, 1], [0, 0], [1],],
            )

            self.assertEqual(
                self.pluck(result, "date"),
                [
                    datetime(2020, 6, 7, 0, tzinfo=pytz.UTC),
                    datetime(2020, 6, 14, 0, tzinfo=pytz.UTC),
                    datetime(2020, 6, 21, 0, tzinfo=pytz.UTC),
                    datetime(2020, 6, 28, 0, tzinfo=pytz.UTC),
                    datetime(2020, 7, 5, 0, tzinfo=pytz.UTC),
                    datetime(2020, 7, 12, 0, tzinfo=pytz.UTC),
                    datetime(2020, 7, 19, 0, tzinfo=pytz.UTC),
                ],
            )

        def test_retention_people(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )

            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = retention().people(
                RetentionFilter(data={"date_to": self._date(10, hour=6), "selected_interval": 2}), self.team
            )
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["id"], person1.pk)

        def test_retention_people_first_time(self):
            _, _, p3, _ = self._create_first_time_retention_events()
            # even if set to hour 6 it should default to beginning of day and include all pageviews above

            target_entity = json.dumps({"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS})
            result = retention().people(
                RetentionFilter(
                    data={
                        "date_to": self._date(10, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "selected_interval": 1,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["id"], p3.pk)

            result = retention().people(
                RetentionFilter(
                    data={
                        "date_to": self._date(14, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "selected_interval": 1,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 0)

        def test_retention_people_paginated(self):
            for i in range(150):
                person_id = "person{}".format(i)
                person_factory(team_id=self.team.pk, distinct_ids=[person_id])
                self._create_events(
                    [
                        (person_id, self._date(0)),
                        (person_id, self._date(1)),
                        (person_id, self._date(2)),
                        (person_id, self._date(5)),
                    ]
                )

            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = self.client.get(
                "/api/person/retention", data={"date_to": self._date(10, hour=6), "selected_interval": 2}
            ).json()

            self.assertEqual(len(result["result"]), 100)

            second_result = self.client.get(result["next"]).json()
            self.assertEqual(len(second_result["result"]), 50)

        def test_retention_invalid_properties(self):
            response = self.client.get("/api/person/retention", data={"properties": "invalid_json"})

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertDictEqual(
                response.json(), self.validation_error_response("Properties are unparsable!", "invalid_input")
            )

        def test_retention_people_in_period(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                    ("person2", self._date(7)),
                ]
            )

            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = retention().people_in_period(
                RetentionFilter(data={"date_to": self._date(10, hour=6), "selected_interval": 2}), self.team
            )

            self.assertEqual(result[0]["person"]["id"], person2.pk)
            self.assertEqual(result[0]["appearances"], [1, 1, 0, 0, 1, 1, 0, 0, 0])

            self.assertEqual(result[1]["person"]["id"], person1.pk)
            self.assertEqual(result[1]["appearances"], [1, 0, 0, 1, 1, 0, 0, 0, 0])

        def test_retention_people_in_period_first_time(self):
            _, _, p3, _ = self._create_first_time_retention_events()
            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            target_entity = json.dumps({"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS})
            result1 = retention().people_in_period(
                RetentionFilter(
                    data={
                        "date_to": self._date(10, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "selected_interval": 0,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result1), 1)
            self.assertEqual(result1[0]["person"]["id"], p3.pk)
            self.assertEqual(result1[0]["appearances"], [1, 1, 0, 1, 1, 1, 0, 0, 0, 0, 0])

            # Make sure later people aren't included
            result2 = retention().people_in_period(
                RetentionFilter(
                    data={
                        "date_to": self._date(10, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "selected_interval": -1,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result2), 2)

        def test_retention_multiple_events(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            person_factory(team_id=self.team.pk, distinct_ids=["person2"])
            person_factory(team_id=self.team.pk, distinct_ids=["person3"])
            person_factory(team_id=self.team.pk, distinct_ids=["person4"])

            first_event = "$some_event"
            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(3)),
                    ("person2", self._date(0)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person3", self._date(5)),
                ],
                first_event,
            )

            self._create_events(
                [("person1", self._date(5)), ("person1", self._date(6)), ("person2", self._date(5)),], "$pageview",
            )

            target_entity = json.dumps({"id": first_event, "type": TREND_FILTER_TYPE_EVENTS})
            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": self._date(6, hour=6),
                        "target_entity": target_entity,
                        "returning_entity": {"id": "$pageview", "type": "events"},
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )
            self.assertEqual(len(result), 7)
            self.assertEqual(
                self.pluck(result, "label"), ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )

            self.assertEqual(
                self.pluck(result, "values", "count"),
                [[2, 0, 0, 0, 0, 2, 1], [2, 0, 0, 0, 2, 1], [2, 0, 0, 2, 1], [2, 0, 2, 1], [0, 0, 0], [1, 0], [0]],
            )

        def test_retention_event_action(self):
            person1 = person_factory(team=self.team, distinct_ids=["person1", "alias1"])
            person2 = person_factory(team=self.team, distinct_ids=["person2"])

            action = self._create_signup_actions(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(3)),
                    ("person2", self._date(0)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                ]
            )

            some_event = "$some_event"
            self._create_events(
                [("person1", self._date(3)), ("person2", self._date(5)),], some_event,
            )

            start_entity = json.dumps({"id": action.pk, "type": TREND_FILTER_TYPE_ACTIONS})
            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": self._date(6, hour=0),
                        "target_entity": start_entity,
                        "returning_entity": {"id": some_event, "type": TREND_FILTER_TYPE_EVENTS},
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 7)
            self.assertEqual(
                self.pluck(result, "label"), ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=pytz.UTC))

            self.assertEqual(
                self.pluck(result, "values", "count"),
                [[2, 0, 0, 1, 0, 1, 0], [2, 0, 1, 0, 1, 0], [2, 1, 0, 1, 0], [2, 0, 1, 0], [0, 0, 0], [0, 0], [0],],
            )

        def test_retention_graph(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(0)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )
            result = retention().run(
                RetentionFilter(data={"date_to": self._date(10, hour=6), "display": TRENDS_LINEAR}), self.team
            )
            self.assertEqual(
                result[0]["count"], 2,
            )
            self.assertEqual(
                result[0]["labels"],
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7", "Day 8", "Day 9", "Day 10"],
            )
            self.assertEqual(
                result[0]["days"],
                [
                    "2020-06-10",
                    "2020-06-11",
                    "2020-06-12",
                    "2020-06-13",
                    "2020-06-14",
                    "2020-06-15",
                    "2020-06-16",
                    "2020-06-17",
                    "2020-06-18",
                    "2020-06-19",
                    "2020-06-20",
                ],
            )
            self.assertEqual(
                result[0]["data"], [100.0, 100.0, 100.0, 50.0, 0.0, 50.0, 100.0, 0.0, 0.0, 0.0, 0.0],
            )

        def test_first_time_retention(self):
            self._create_first_time_retention_events()

            target_entity = json.dumps({"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS})
            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": self._date(5, hour=6),
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
                self.pluck(result, "label"), ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )

            self.assertEqual(
                self.pluck(result, "values", "count"),
                [[2, 1, 2, 2, 1, 0, 1], [1, 1, 0, 1, 1, 1], [0, 0, 0, 0, 0], [1, 1, 0, 1], [0, 0, 0], [0, 0], [0]],
            )

        def test_retention_with_properties(self):

            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )

            result = retention().run(
                RetentionFilter(
                    data={
                        "properties": [{"key": "$some_property", "value": "value"}],
                        "date_to": self._date(10, hour=0),
                    }
                ),
                self.team,
            )
            self.assertEqual(len(result), 11)
            self.assertEqual(
                self.pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7", "Day 8", "Day 9", "Day 10",],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=pytz.UTC))

            self.assertEqual(
                self.pluck(result, "values", "count"),
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
            person1 = person_factory(
                team_id=self.team.pk, distinct_ids=["person1", "alias1"], properties={"email": "person1@test.com"},
            )
            person2 = person_factory(
                team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "person2@test.com"},
            )

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )

            result = retention().run(
                RetentionFilter(
                    data={
                        "properties": [{"key": "email", "value": "person1@test.com", "type": "person",}],
                        "date_to": self._date(6, hour=0),
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 7)
            self.assertEqual(
                self.pluck(result, "label"), ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=pytz.UTC))
            self.assertEqual(
                self.pluck(result, "values", "count"),
                [[1, 1, 1, 0, 0, 1, 1], [1, 1, 0, 0, 1, 1], [1, 0, 0, 1, 1], [0, 0, 0, 0], [0, 0, 0], [1, 1], [1],],
            )

        def test_retention_action_start_point(self):
            person1 = person_factory(team=self.team, distinct_ids=["person1", "alias1"])
            person2 = person_factory(team=self.team, distinct_ids=["person2"])

            action = self._create_signup_actions(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )

            start_entity = json.dumps({"id": action.pk, "type": TREND_FILTER_TYPE_ACTIONS})
            result = retention().run(
                RetentionFilter(
                    data={
                        "date_to": self._date(6, hour=0),
                        "target_entity": start_entity,
                        "actions": [{"id": action.pk, "type": TREND_FILTER_TYPE_ACTIONS},],
                        "total_intervals": 7,
                    }
                ),
                self.team,
            )

            self.assertEqual(len(result), 7)
            self.assertEqual(
                self.pluck(result, "label"), ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=pytz.UTC))

            self.assertEqual(
                self.pluck(result, "values", "count"),
                [[1, 1, 1, 0, 0, 1, 1], [2, 2, 1, 0, 1, 2], [2, 1, 0, 1, 2], [1, 0, 0, 1], [0, 0, 0], [1, 1], [2],],
            )

        def test_filter_test_accounts(self):
            person1 = person_factory(
                team_id=self.team.pk, distinct_ids=["person1", "alias1"], properties={"email": "test@posthog.com"}
            )
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )

            # even if set to hour 6 it should default to beginning of day and include all pageviews above
            result = retention().run(
                RetentionFilter(data={"date_to": self._date(10, hour=6), FILTER_TEST_ACCOUNTS: True}, team=self.team),
                self.team,
            )
            self.assertEqual(len(result), 11)
            self.assertEqual(
                self.pluck(result, "label"),
                ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7", "Day 8", "Day 9", "Day 10",],
            )
            self.assertEqual(result[0]["date"], datetime(2020, 6, 10, 0, tzinfo=pytz.UTC))

            self.assertEqual(
                self.pluck(result, "values", "count"),
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

        def _create_events(self, user_and_timestamps, event="$pageview"):
            i = 0
            for (distinct_id, timestamp, *properties_args) in user_and_timestamps:
                properties = {"$some_property": "value"} if i % 2 == 0 else {}
                if len(properties_args) == 1:
                    properties.update(properties_args[0])

                event_factory(
                    team=self.team, event=event, distinct_id=distinct_id, timestamp=timestamp, properties=properties,
                )
                i += 1

        def _create_first_time_retention_events(self):
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            p2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])
            p3 = person_factory(team_id=self.team.pk, distinct_ids=["person3"])
            p4 = person_factory(team_id=self.team.pk, distinct_ids=["person4"])
            person_factory(team_id=self.team.pk, distinct_ids=["shouldnt_include"])

            self._create_events(
                [
                    ("shouldnt_include", self._date(-5)),
                    ("shouldnt_include", self._date(-1)),
                    ("person1", self._date(-1)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(3)),
                    ("person1", self._date(4)),
                    ("person2", self._date(-1)),
                ],
                "$user_signed_up",
            )

            self._create_events(
                [
                    ("person1", self._date(0)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(5)),
                    ("alias1", self._date(5, 9)),
                    ("person1", self._date(6)),
                    ("person2", self._date(1)),
                    ("person2", self._date(2)),
                    ("person2", self._date(3)),
                    ("person2", self._date(6)),
                ]
            )

            self._create_events([("person3", self._date(0))], "$user_signed_up")

            self._create_events(
                [
                    ("person3", self._date(1)),
                    ("person3", self._date(3)),
                    ("person3", self._date(4)),
                    ("person3", self._date(5)),
                ]
            )

            self._create_events([("person4", self._date(2))], "$user_signed_up")

            self._create_events(
                [("person4", self._date(3)), ("person4", self._date(5)),]
            )

            return p1, p2, p3, p4

        def _create_signup_actions(self, user_and_timestamps):

            for distinct_id, timestamp in user_and_timestamps:
                event_factory(
                    team=self.team, event="sign up", distinct_id=distinct_id, timestamp=timestamp,
                )
            sign_up_action = action_factory(team=self.team, name="sign up")
            return sign_up_action

        def _date(self, day, hour=5, month=0):
            return datetime(2020, 6 + month, 10 + day, hour, tzinfo=pytz.UTC).isoformat()

        def pluck(self, list_of_dicts, key, child_key=None):
            return [self.pluck(d[key], child_key) if child_key else d[key] for d in list_of_dicts]

    return TestRetention


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    action.calculate_events()
    return action


class TestDjangoRetention(retention_test_factory(Retention, Event.objects.create, Person.objects.create, _create_action)):  # type: ignore
    pass
