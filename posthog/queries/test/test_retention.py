import json
from datetime import datetime

import pytz

from posthog.api.test.base import BaseTest
from posthog.constants import RETENTION_FIRST_TIME, RETENTION_TYPE, TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models import Action, ActionStep, Event, Filter, Person
from posthog.queries.retention import Retention


# parameterize tests to reuse in EE
def retention_test_factory(retention, event_factory, person_factory, action_factory):
    class TestRetention(BaseTest):
        def test_retention_default(self):
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

            result = retention().run(Filter(data={"dummy": "dummy"}), self.team)
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

        def test_retention(self):
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
            result = retention().run(Filter(data={"date_to": self._date(10, hour=6)}), self.team)
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

        def test_first_user_retention(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person1", "alias1"])
            person_factory(team_id=self.team.pk, distinct_ids=["person2"])
            person_factory(team_id=self.team.pk, distinct_ids=["person3"])
            person_factory(team_id=self.team.pk, distinct_ids=["person4"])

            self._create_events(
                [
                    ("person1", self._date(-1)),
                    ("person1", self._date(1)),
                    ("person1", self._date(2)),
                    ("person1", self._date(3)),
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

            target_entity = json.dumps({"id": "$user_signed_up", "type": TREND_FILTER_TYPE_EVENTS})
            result = retention().run(
                Filter(
                    data={
                        "date_to": self._date(5, hour=6),
                        RETENTION_TYPE: RETENTION_FIRST_TIME,
                        "target_entity": target_entity,
                        "events": [{"id": "$pageview", "type": "events"},],
                    }
                ),
                self.team,
                total_intervals=7,
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
                Filter(
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
                Filter(
                    data={
                        "properties": [{"key": "email", "value": "person1@test.com", "type": "person",}],
                        "date_to": self._date(6, hour=0),
                    }
                ),
                self.team,
                total_intervals=7,
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
                Filter(data={"date_to": self._date(6, hour=0), "target_entity": start_entity,}),
                self.team,
                total_intervals=7,
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

        def test_retention_period_monthly(self):
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

            filter = Filter(data={"date_to": self._date(0, month=5, hour=0), "period": "Month"})

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

        def test_retention_period_weekly(self):
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
                Filter(data={"date_to": self._date(10, month=1, hour=0), "period": "Week"}),
                self.team,
                total_intervals=7,
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

        def test_retention_period_hourly(self):
            Person.objects.create(
                team=self.team, distinct_ids=["person1", "alias1"], properties={"email": "person1@test.com"},
            )
            Person.objects.create(
                team=self.team, distinct_ids=["person2"], properties={"email": "person2@test.com"},
            )

            self._create_events(
                [
                    ("person1", self._date(day=0, hour=0)),
                    ("person2", self._date(day=0, hour=0)),
                    ("person1", self._date(day=0, hour=1)),
                    ("person2", self._date(day=0, hour=1)),
                    ("person1", self._date(day=0, hour=2)),
                    ("person2", self._date(day=0, hour=2)),
                    ("person1", self._date(day=0, hour=4)),
                    ("person1", self._date(day=0, hour=5)),
                    ("person2", self._date(day=0, hour=5)),
                    ("person2", self._date(day=0, hour=6)),
                    ("person1", self._date(day=0, hour=8)),
                    ("person2", self._date(day=0, hour=10)),
                ]
            )

            filter = Filter(data={"date_to": self._date(0, hour=10), "period": "Hour"})

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
                    datetime(2020, 6, 10, 0, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 1, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 2, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 3, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 4, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 5, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 6, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 7, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 8, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 9, tzinfo=pytz.UTC),
                    datetime(2020, 6, 10, 10, tzinfo=pytz.UTC),
                ],
            )

        def _create_events(self, user_and_timestamps, event="$pageview"):
            i = 0
            for distinct_id, timestamp in user_and_timestamps:
                properties = {"$some_property": "value"} if i % 2 == 0 else {}
                event_factory(
                    team=self.team, event=event, distinct_id=distinct_id, timestamp=timestamp, properties=properties,
                )
                i += 1

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
