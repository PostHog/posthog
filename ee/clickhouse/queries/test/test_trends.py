from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.queries.test.test_trends import trend_test_factory


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups)
    return cohort


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


# override tests from test facotry if intervals are different
class TestClickhouseTrends(ClickhouseTestMixin, trend_test_factory(ClickhouseTrends, _create_event, Person.objects.create, _create_action, _create_cohort)):  # type: ignore
    def test_interval_rounding(self):
        self._test_events_with_dates(
            dates=["2020-11-01", "2020-11-10", "2020-11-11", "2020-11-18"],
            interval="week",
            date_from="2020-11-04",
            date_to="2020-11-24",
            result=[
                {
                    "action": {
                        "id": "event_name",
                        "type": "events",
                        "order": None,
                        "name": "event_name",
                        "math": None,
                        "math_property": None,
                        "properties": [],
                    },
                    "label": "event_name",
                    "count": 4.0,
                    "data": [1.0, 2.0, 1.0, 0.0],
                    "labels": ["Sun. 1 November", "Sun. 8 November", "Sun. 15 November", "Sun. 22 November"],
                    "days": ["2020-11-01", "2020-11-08", "2020-11-15", "2020-11-22"],
                }
            ],
        )

    def test_breakdown_by_person_property(self):
        person1, person2, person3, person4 = self._create_multiple_people()
        action = _create_action(name="watched movie", team=self.team)

        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "name",
                        "breakdown_type": "person",
                        "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                    }
                ),
                self.team,
            )
            event_response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "name",
                        "breakdown_type": "person",
                        "events": [{"id": "watched movie", "name": "watched movie", "type": "events", "order": 0,}],
                    }
                ),
                self.team,
            )

        self.assertListEqual([res["breakdown_value"] for res in event_response], ["person1", "person2", "person3"])

        for response in event_response:
            if response["breakdown_value"] == "person1":
                self.assertEqual(response["count"], 1)
                self.assertEqual(response["label"], "watched movie - person1")
            if response["breakdown_value"] == "person2":
                self.assertEqual(response["count"], 3)
            if response["breakdown_value"] == "person3":
                self.assertEqual(response["count"], 3)

        self.assertTrue(self._compare_entity_response(event_response, action_response,))

    def test_breakdown_filtering(self):
        self._create_events()
        # test breakdown filtering
        with freeze_time("2020-01-04T13:01:01Z"):
            response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "$some_property",
                        "events": [
                            {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                            {"id": "no events"},
                        ],
                    }
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "sign up - value")
        self.assertEqual(response[1]["label"], "sign up - other_value")
        self.assertEqual(response[2]["label"], "no events - value")
        self.assertEqual(response[3]["label"], "no events - other_value")

        self.assertEqual(sum(response[0]["data"]), 2)
        self.assertEqual(response[0]["breakdown_value"], "value")

        self.assertEqual(sum(response[1]["data"]), 1)
        self.assertEqual(response[1]["breakdown_value"], "other_value")

    def test_breakdown_filtering_with_properties(self):
        with freeze_time("2020-01-03T13:01:01Z"):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "first url", "$browser": "Firefox", "$os": "Mac"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "first url", "$browser": "Chrome", "$os": "Windows"},
            )
        with freeze_time("2020-01-04T13:01:01Z"):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "second url", "$browser": "Firefox", "$os": "Mac"},
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "second url", "$browser": "Chrome", "$os": "Windows"},
            )

        with freeze_time("2020-01-05T13:01:01Z"):
            response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "$current_url",
                        "events": [
                            {
                                "id": "sign up",
                                "name": "sign up",
                                "type": "events",
                                "order": 0,
                                "properties": [{"key": "$os", "value": "Mac"}],
                            },
                        ],
                        "properties": [{"key": "$browser", "value": "Firefox"}],
                    }
                ),
                self.team,
            )

        self.assertEqual(response[0]["label"], "sign up - second url")
        self.assertEqual(response[1]["label"], "sign up - first url")

        self.assertEqual(sum(response[0]["data"]), 1)
        self.assertEqual(response[0]["breakdown_value"], "second url")

        self.assertEqual(sum(response[1]["data"]), 1)
        self.assertEqual(response[1]["breakdown_value"], "first url")

    def test_dau_with_breakdown_filtering(self):
        sign_up_action, _ = self._create_events()
        with freeze_time("2020-01-02T13:01:01Z"):
            _create_event(
                team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "other_value"},
            )
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = ClickhouseTrends().run(
                Filter(data={"breakdown": "$some_property", "actions": [{"id": sign_up_action.id, "math": "dau"}]}),
                self.team,
            )
            event_response = ClickhouseTrends().run(
                Filter(data={"breakdown": "$some_property", "events": [{"id": "sign up", "math": "dau"}]}), self.team,
            )

        self.assertEqual(event_response[0]["label"], "sign up - value")
        self.assertEqual(event_response[1]["label"], "sign up - other_value")

        self.assertEqual(sum(event_response[0]["data"]), 1)
        self.assertEqual(event_response[0]["data"][4], 1)  # property not defined

        self.assertEqual(sum(event_response[1]["data"]), 1)
        self.assertEqual(event_response[1]["data"][5], 1)
        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_dau_with_breakdown_filtering_with_prop_filter(self):
        sign_up_action, _ = self._create_events()
        with freeze_time("2020-01-02T13:01:01Z"):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "other_value", "$os": "Windows"},
            )
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = ClickhouseTrends().run(
                Filter(
                    data={
                        "breakdown": "$some_property",
                        "actions": [{"id": sign_up_action.id, "math": "dau"}],
                        "properties": [{"key": "$os", "value": "Windows"}],
                    }
                ),
                self.team,
            )
            event_response = ClickhouseTrends().run(
                Filter(
                    data={
                        "breakdown": "$some_property",
                        "events": [{"id": "sign up", "math": "dau"}],
                        "properties": [{"key": "$os", "value": "Windows"}],
                    }
                ),
                self.team,
            )

        self.assertEqual(event_response[0]["label"], "sign up - value")
        self.assertEqual(event_response[1]["label"], "sign up - other_value")

        self.assertEqual(sum(event_response[1]["data"]), 1)
        self.assertEqual(event_response[1]["data"][5], 1)  # property not defined

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    # this ensures that the properties don't conflict when formatting params
    def test_action_with_prop(self):
        person = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
        )
        sign_up_action = Action.objects.create(team=self.team, name="sign up")
        ActionStep.objects.create(
            action=sign_up_action, event="sign up", properties={"$current_url": "https://posthog.com/feedback/1234"}
        )

        with freeze_time("2020-01-02T13:01:01Z"):
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$current_url": "https://posthog.com/feedback/1234"},
            )

        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = ClickhouseTrends().run(
                Filter(
                    data={
                        "actions": [{"id": sign_up_action.id, "math": "dau"}],
                        "properties": [{"key": "$current_url", "value": "fake"}],
                    }
                ),
                self.team,
            )

        # if the params were shared it would be 1 because action would take precedence
        self.assertEqual(action_response[0]["count"], 0)
