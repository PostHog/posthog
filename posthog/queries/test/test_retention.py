from posthog.queries.stickiness import Stickiness
from posthog.api.test.base import BaseTest
from posthog.queries.retention import Retention
from posthog.models import Action, Person, Event, ActionStep, Team, Filter, Entity
from freezegun import freeze_time
from datetime import datetime
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
import pytz


class TestRetention(BaseTest):
    def test_retention(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person1", "alias1"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["person2"])

        self._create_pageviews(
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

        result = Retention().run(Filter(data={"date_from": self._date(0, hour=0)}), self.team, total_days=7)

        self.assertEqual(len(result["data"]), 7)
        self.assertEqual(
            self.pluck(result["data"], "label"), ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result["data"][0]["date"], "Wed. 10 June")

        self.assertEqual(
            self.pluck(result["data"], "values", "count"),
            [[1, 1, 1, 0, 0, 1, 1], [2, 2, 1, 0, 1, 2], [2, 1, 0, 1, 2], [1, 0, 0, 1], [0, 0, 0], [1, 1], [2],],
        )

    def test_retention_with_properties(self):
        person1 = Person.objects.create(
            team=self.team, distinct_ids=["person1", "alias1"], properties={"email": "person1@test.com"}
        )
        person2 = Person.objects.create(
            team=self.team, distinct_ids=["person2"], properties={"email": "person2@test.com"}
        )

        self._create_pageviews(
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

        result = Retention().run(
            Filter(
                data={
                    "properties": [{"key": "email", "value": "person1@test.com", "type": "person"}],
                    "date_from": self._date(0, hour=0),
                }
            ),
            self.team,
            total_days=7,
        )

        self.assertEqual(len(result["data"]), 7)
        self.assertEqual(
            self.pluck(result["data"], "label"), ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result["data"][0]["date"], "Wed. 10 June")
        self.assertEqual(
            self.pluck(result["data"], "values", "count"),
            [[1, 1, 1, 0, 0, 1, 1], [1, 1, 0, 0, 1, 1], [1, 0, 0, 1, 1], [0, 0, 0, 0], [0, 0, 0], [1, 1], [1]],
        )

    def test_retention_action_start_point(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person1", "alias1"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["person2"])

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

        start_entity = Entity({"id": action.pk, "type": TREND_FILTER_TYPE_ACTIONS})
        result = Retention().run(
            Filter(data={"date_from": self._date(0, hour=0), "entities": [start_entity]}), self.team, total_days=7
        )

        self.assertEqual(len(result["data"]), 7)
        self.assertEqual(
            self.pluck(result["data"], "label"), ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result["data"][0]["date"], "Wed. 10 June")

        self.assertEqual(
            self.pluck(result["data"], "values", "count"),
            [[1, 1, 1, 0, 0, 1, 1], [2, 2, 1, 0, 1, 2], [2, 1, 0, 1, 2], [1, 0, 0, 1], [0, 0, 0], [1, 1], [2],],
        )

    def _create_pageviews(self, user_and_timestamps):
        for distinct_id, timestamp in user_and_timestamps:
            Event.objects.create(
                team=self.team, event="$pageview", distinct_id=distinct_id, timestamp=timestamp,
            )

    def _create_signup_actions(self, user_and_timestamps):
        sign_up_action = Action.objects.create(team=self.team, name="sign up")
        ActionStep.objects.create(action=sign_up_action, event="sign up")
        for distinct_id, timestamp in user_and_timestamps:
            Event.objects.create(
                team=self.team, event="sign up", distinct_id=distinct_id, timestamp=timestamp,
            )
        return sign_up_action

    def _date(self, day, hour=5):
        return datetime(2020, 6, 10 + day, hour, tzinfo=pytz.UTC).isoformat()

    def pluck(self, list_of_dicts, key, child_key=None):
        return [self.pluck(d[key], child_key) if child_key else d[key] for d in list_of_dicts]
