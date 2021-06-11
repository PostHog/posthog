from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import create_person, create_person_distinct_id
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import TRENDS_BAR_VALUE
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.queries.test.test_trends import trend_test_factory


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name, properties=properties)
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
    def test_breakdown_with_filter(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"email": "test@posthog.com"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "test@gmail.com"})
        _create_event(event="sign up", distinct_id="person1", team=self.team, properties={"key": "val"})
        _create_event(event="sign up", distinct_id="person2", team=self.team, properties={"key": "oh"})
        response = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "-14d",
                    "breakdown": "key",
                    "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                    "properties": [{"key": "key", "value": "oh", "operator": "not_icontains"}],
                }
            ),
            self.team,
        )
        self.assertEqual(len(response), 2)
        self.assertEqual(response[1]["breakdown_value"], "val")

    def test_breakdown_filtering_limit(self):
        self._create_breakdown_events()
        with freeze_time("2020-01-04T13:01:01Z"):
            response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "$some_property",
                        "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
                    }
                ),
                self.team,
            )
        self.assertEqual(len(response), 26)  # We fetch 25 to see if there are more ethan 20 values

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

        self.assertListEqual(
            [res["breakdown_value"] for res in event_response], ["none", "person1", "person2", "person3"]
        )

        for response in event_response:
            if response["breakdown_value"] == "person1":
                self.assertEqual(response["count"], 1)
                self.assertEqual(response["label"], "watched movie - person1")
            if response["breakdown_value"] == "person2":
                self.assertEqual(response["count"], 3)
            if response["breakdown_value"] == "person3":
                self.assertEqual(response["count"], 3)

        self.assertEntityResponseEqual(
            event_response, action_response,
        )

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

        self.assertEqual(response[0]["label"], "sign up - none")
        self.assertEqual(response[1]["label"], "sign up - value")
        self.assertEqual(response[2]["label"], "sign up - other_value")
        self.assertEqual(response[3]["label"], "no events - none")

        self.assertEqual(sum(response[0]["data"]), 2)
        self.assertEqual(sum(response[1]["data"]), 2)
        self.assertEqual(sum(response[2]["data"]), 1)
        self.assertEqual(sum(response[3]["data"]), 1)

    def test_breakdown_filtering_persons(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"email": "test@posthog.com"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "test@gmail.com"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person3"], properties={})

        _create_event(event="sign up", distinct_id="person1", team=self.team, properties={"key": "val"})
        _create_event(event="sign up", distinct_id="person2", team=self.team, properties={"key": "val"})
        _create_event(event="sign up", distinct_id="person3", team=self.team, properties={"key": "val"})
        response = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "-14d",
                    "breakdown": "email",
                    "breakdown_type": "person",
                    "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,},],
                }
            ),
            self.team,
        )
        self.assertEqual(response[0]["label"], "sign up - none")
        self.assertEqual(response[1]["label"], "sign up - test@gmail.com")
        self.assertEqual(response[2]["label"], "sign up - test@posthog.com")

        self.assertEqual(response[0]["count"], 1)
        self.assertEqual(response[1]["count"], 1)
        self.assertEqual(response[2]["count"], 1)

    # ensure that column names are properly handled when subqueries and person subquery share properties column
    def test_breakdown_filtering_persons_with_action_props(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"email": "test@posthog.com"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "test@gmail.com"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person3"], properties={})

        _create_event(event="sign up", distinct_id="person1", team=self.team, properties={"key": "val"})
        _create_event(event="sign up", distinct_id="person2", team=self.team, properties={"key": "val"})
        _create_event(event="sign up", distinct_id="person3", team=self.team, properties={"key": "val"})
        action = _create_action(
            name="sign up",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )
        response = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "-14d",
                    "breakdown": "email",
                    "breakdown_type": "person",
                    "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                }
            ),
            self.team,
        )
        self.assertEqual(response[0]["label"], "sign up - none")
        self.assertEqual(response[1]["label"], "sign up - test@gmail.com")
        self.assertEqual(response[2]["label"], "sign up - test@posthog.com")

        self.assertEqual(response[0]["count"], 1)
        self.assertEqual(response[1]["count"], 1)
        self.assertEqual(response[2]["count"], 1)

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

        self.assertEqual(response[1]["label"], "sign up - second url")
        self.assertEqual(response[2]["label"], "sign up - first url")

        self.assertEqual(sum(response[1]["data"]), 1)
        self.assertEqual(response[1]["breakdown_value"], "second url")

        self.assertEqual(sum(response[2]["data"]), 1)
        self.assertEqual(response[2]["breakdown_value"], "first url")

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

        self.assertEqual(event_response[1]["label"], "sign up - value")
        self.assertEqual(event_response[2]["label"], "sign up - other_value")

        self.assertEqual(sum(event_response[1]["data"]), 1)
        self.assertEqual(event_response[1]["data"][4], 1)  # property not defined

        self.assertEqual(sum(event_response[2]["data"]), 1)
        self.assertEqual(event_response[2]["data"][5], 1)
        self.assertEntityResponseEqual(action_response, event_response)

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

        self.assertEqual(event_response[1]["label"], "sign up - other_value")

        self.assertEqual(sum(event_response[1]["data"]), 1)
        self.assertEqual(event_response[1]["data"][5], 1)  # property not defined

        self.assertEntityResponseEqual(action_response, event_response)

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

    def test_combine_all_cohort_and_icontains(self):
        # This caused some issues with SQL parsing
        sign_up_action, _ = self._create_events()
        cohort = Cohort.objects.create(team=self.team, name="a", groups=[{"properties": {"key": "value"}}])
        action_response = ClickhouseTrends().run(
            Filter(
                data={
                    "actions": [{"id": sign_up_action.id, "math": "dau"}],
                    "properties": [{"key": "$current_url", "value": "ii", "operator": "icontains"}],
                    "breakdown": [cohort.pk, "all"],
                    "breakdown_type": "cohort",
                }
            ),
            self.team,
        )
        self.assertEqual(action_response[0]["count"], 0)

    def test_breakdown_user_props_with_filter(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"email": "test@posthog.com"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "test@gmail.com"})
        person = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["person3"], properties={"email": "test@gmail.com"}
        )
        create_person_distinct_id(person.id, self.team.pk, "person1", str(person.uuid))

        _create_event(event="sign up", distinct_id="person1", team=self.team, properties={"key": "val"})
        _create_event(event="sign up", distinct_id="person2", team=self.team, properties={"key": "val"})
        response = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "-14d",
                    "breakdown": "email",
                    "breakdown_type": "person",
                    "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                    "properties": [
                        {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
                        {"key": "key", "value": "val"},
                    ],
                }
            ),
            self.team,
        )
        self.assertEqual(len(response), 2)
        self.assertEqual(response[1]["breakdown_value"], "test@gmail.com")

    def _create_active_user_events(self):
        p0 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p0"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p0",
            timestamp="2020-01-03T12:00:00Z",
            properties={"key": "val"},
        )

        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

    def test_active_user_math(self):
        self._create_active_user_events()

        data = {
            "date_from": "2020-01-09T00:00:00Z",
            "date_to": "2020-01-16T00:00:00Z",
            "events": [{"id": "$pageview", "type": "events", "order": 0, "math": "weekly_active"}],
        }

        filter = Filter(data=data)
        result = ClickhouseTrends().run(filter, self.team,)
        self.assertEqual(result[0]["data"], [3.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_active_user_math_action(self):
        action = _create_action(name="$pageview", team=self.team)
        self._create_active_user_events()

        data = {
            "date_from": "2020-01-09T00:00:00Z",
            "date_to": "2020-01-16T00:00:00Z",
            "actions": [{"id": action.id, "type": "actions", "order": 0, "math": "weekly_active"}],
        }

        filter = Filter(data=data)
        result = ClickhouseTrends().run(filter, self.team,)
        self.assertEqual(result[0]["data"], [3.0, 2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_breakdown_active_user_math(self):

        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-10T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-09T12:00:00Z",
            properties={"key": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        data = {
            "date_from": "2020-01-01T00:00:00Z",
            "date_to": "2020-01-12T00:00:00Z",
            "breakdown": "key",
            "events": [{"id": "$pageview", "type": "events", "order": 0, "math": "weekly_active"}],
        }

        filter = Filter(data=data)
        result = ClickhouseTrends().run(filter, self.team,)
        self.assertEqual(result[1]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0, 0.0])

    def test_filter_test_accounts(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-11T12:00:00Z",
            properties={"key": "val"},
        )
        self.team.test_account_filters = [{"key": "name", "value": "p1", "operator": "is_not", "type": "person"}]
        self.team.save()
        data = {
            "date_from": "2020-01-01T00:00:00Z",
            "date_to": "2020-01-12T00:00:00Z",
            "events": [{"id": "$pageview", "type": "events", "order": 0}],
            "filter_test_accounts": "true",
        }
        filter = Filter(data=data)
        filter_2 = Filter(data={**data, "filter_test_accounts": "false",})
        filter_3 = Filter(data={**data, "breakdown": "key"})
        result = ClickhouseTrends().run(filter, self.team,)
        self.assertEqual(result[0]["count"], 1)
        result = ClickhouseTrends().run(filter_2, self.team,)
        self.assertEqual(result[0]["count"], 2)
        result = ClickhouseTrends().run(filter_3, self.team,)
        self.assertEqual(result[1]["count"], 1)

    def test_breakdown_filtering_bar_chart_by_value(self):
        self._create_events()

        # test breakdown filtering
        with freeze_time("2020-01-04T13:01:01Z"):
            response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-7d",
                        "breakdown": "$some_property",
                        "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,},],
                        "display": TRENDS_BAR_VALUE,
                    }
                ),
                self.team,
            )

        self.assertEqual(response[0]["aggregated_value"], 1)
        self.assertEqual(response[1]["aggregated_value"], 1)
        self.assertEqual(
            response[0]["days"],
            [
                "2019-12-28",
                "2019-12-29",
                "2019-12-30",
                "2019-12-31",
                "2020-01-01",
                "2020-01-02",
                "2020-01-03",
                "2020-01-04",
            ],
        )
