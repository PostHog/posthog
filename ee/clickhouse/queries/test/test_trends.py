from uuid import uuid4

from django.utils import timezone
from freezegun import freeze_time
from rest_framework.exceptions import ValidationError

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.group import create_group
from ee.clickhouse.models.person import create_person_distinct_id
from ee.clickhouse.queries.trends.clickhouse_trends import ClickhouseTrends
from ee.clickhouse.queries.trends.person import TrendsPersonQuery
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.constants import TRENDS_BAR_VALUE
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person
from posthog.queries.test.test_trends import trend_test_factory
from posthog.test.base import test_with_materialized_columns


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
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, last_calculation=timezone.now())
    return cohort


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


# override tests from test facotry if intervals are different
class TestClickhouseTrends(ClickhouseTestMixin, trend_test_factory(ClickhouseTrends, _create_event, Person.objects.create, _create_action, _create_cohort)):  # type: ignore

    maxDiff = None

    def _get_trend_people(self, filter, entity):
        result = TrendsPersonQuery(filter=filter, entity=entity, team=self.team).get_people()
        return result

    def _create_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:7", properties={"industry": "finance"})
        create_group(
            team_id=self.team.pk, group_type_index=1, group_key="company:10", properties={"industry": "finance"}
        )

    @test_with_materialized_columns(["key"])
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
        self.assertEqual(len(response), 1)
        # don't return none option when empty
        self.assertEqual(response[0]["breakdown_value"], "val")

    @snapshot_clickhouse_queries
    def test_breakdown_with_filter_groups(self):
        self._create_groups()

        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "oh", "$group_0": "org:7", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )

        response = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "2020-01-01T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown": "key",
                    "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                    "properties": [{"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}],
                }
            ),
            self.team,
        )

        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["breakdown_value"], "oh")
        self.assertEqual(response[0]["count"], 1)
        self.assertEqual(response[1]["breakdown_value"], "uh")
        self.assertEqual(response[1]["count"], 1)

    @snapshot_clickhouse_queries
    def test_breakdown_by_group_props(self):
        self._create_groups()

        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:7", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )

        response = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "2020-01-01T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown": "industry",
                    "breakdown_type": "group",
                    "breakdown_group_type_index": 0,
                    "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                }
            ),
            self.team,
        )

        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["breakdown_value"], "finance")
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[1]["breakdown_value"], "technology")
        self.assertEqual(response[1]["count"], 1)

    @snapshot_clickhouse_queries
    def test_breakdown_by_group_props_with_person_filter(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})

        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
        )

        response = ClickhouseTrends().run(
            Filter(
                data={
                    "date_from": "2020-01-01T00:00:00Z",
                    "date_to": "2020-01-12T00:00:00Z",
                    "breakdown": "industry",
                    "breakdown_type": "group",
                    "breakdown_group_type_index": 0,
                    "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                    "properties": [{"key": "key", "value": "value", "type": "person"}],
                }
            ),
            self.team,
        )

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["breakdown_value"], "finance")
        self.assertEqual(response[0]["count"], 1)

    @test_with_materialized_columns(["$some_property"])
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
        self.assertEqual(len(response), 25)  # We fetch 25 to see if there are more ethan 20 values

    @test_with_materialized_columns(event_properties=["order"], person_properties=["name"])
    def test_breakdown_with_person_property_filter(self):
        self._create_multiple_people()
        action = _create_action(name="watched movie", team=self.team)

        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "order",
                        "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                        "properties": [{"key": "name", "value": "person2", "type": "person"}],
                    }
                ),
                self.team,
            )
            event_response = ClickhouseTrends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "order",
                        "events": [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                                "properties": [{"key": "name", "value": "person2", "type": "person"}],
                            }
                        ],
                    }
                ),
                self.team,
            )

        self.assertDictContainsSubset({"count": 2, "breakdown_value": "2",}, event_response[0])
        self.assertDictContainsSubset({"count": 1, "breakdown_value": "1",}, event_response[1])
        self.assertEntityResponseEqual(event_response, action_response)

    @test_with_materialized_columns(["$some_property"])
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

    @test_with_materialized_columns(person_properties=["email"])
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
    @test_with_materialized_columns(event_properties=["key"], person_properties=["email"])
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

    @test_with_materialized_columns(["$current_url", "$os", "$browser"])
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

        response = sorted(response, key=lambda x: x["label"])
        self.assertEqual(response[0]["label"], "sign up - first url")
        self.assertEqual(response[1]["label"], "sign up - second url")

        self.assertEqual(sum(response[0]["data"]), 1)
        self.assertEqual(response[0]["breakdown_value"], "first url")

        self.assertEqual(sum(response[1]["data"]), 1)
        self.assertEqual(response[1]["breakdown_value"], "second url")

    @test_with_materialized_columns(["$some_property"])
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

    @test_with_materialized_columns(["$os", "$some_property"])
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

        self.assertEqual(event_response[0]["label"], "sign up - other_value")

        self.assertEqual(sum(event_response[0]["data"]), 1)
        self.assertEqual(event_response[0]["data"][5], 1)  # property not defined

        self.assertEntityResponseEqual(action_response, event_response)

    @test_with_materialized_columns(event_properties=["$host"], person_properties=["$some_prop"])
    def test_against_clashing_entity_and_property_filter_naming(self):
        # Regression test for https://github.com/PostHog/posthog/issues/5814
        Person.objects.create(
            team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="blabla",
            properties={"$host": "app.example.com"},
            timestamp="2020-01-03T12:00:00Z",
        )

        with freeze_time("2020-01-04T13:01:01Z"):
            response = ClickhouseTrends().run(
                Filter(
                    data={
                        "events": [
                            {
                                "id": "$pageview",
                                "properties": [{"key": "$host", "operator": "icontains", "value": ".com"}],
                            }
                        ],
                        "properties": [{"key": "$host", "value": ["app.example.com", "another.com"]}],
                        "breakdown": "$some_prop",
                        "breakdown_type": "person",
                    }
                ),
                self.team,
            )

        self.assertEqual(response[0]["count"], 1)

    # this ensures that the properties don't conflict when formatting params
    @test_with_materialized_columns(["$current_url"])
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

    @test_with_materialized_columns(["$current_url"], verify_no_jsonextract=False)
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

    @test_with_materialized_columns(event_properties=["key"], person_properties=["email"])
    def test_breakdown_user_props_with_filter(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"email": "test@posthog.com"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "test@gmail.com"})
        person = Person.objects.create(
            team_id=self.team.pk, distinct_ids=["person3"], properties={"email": "test@gmail.com"}
        )
        create_person_distinct_id(self.team.pk, "person1", str(person.uuid))

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

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["breakdown_value"], "test@gmail.com")

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

    @test_with_materialized_columns(["key"])
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
        self.assertEqual(result[0]["data"], [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 2.0, 2.0, 0.0])

    @test_with_materialized_columns(event_properties=["key"], person_properties=["name"])
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
        filter = Filter(
            {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "filter_test_accounts": "true",
            },
            team=self.team,
        )
        result = ClickhouseTrends().run(filter, self.team,)
        self.assertEqual(result[0]["count"], 1)
        filter2 = Filter(
            {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
            },
            team=self.team,
        )
        result = ClickhouseTrends().run(filter2, self.team,)
        self.assertEqual(result[0]["count"], 2)
        result = ClickhouseTrends().run(filter.with_data({"breakdown": "key"}), self.team,)
        self.assertEqual(result[0]["count"], 1)

    @test_with_materialized_columns(["$some_property"])
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

        self.assertEqual(response[0]["aggregated_value"], 2)  # the events without breakdown value
        self.assertEqual(response[1]["aggregated_value"], 1)
        self.assertEqual(response[2]["aggregated_value"], 1)
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

    @test_with_materialized_columns(person_properties=["key", "key_2"], verify_no_jsonextract=False)
    def test_breakdown_multiple_cohorts(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "value"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"key_2": "value_2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        p3 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p3"], properties={"key_2": "value_2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        cohort1 = _create_cohort(
            team=self.team,
            name="cohort_1",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )
        cohort2 = _create_cohort(
            team=self.team,
            name="cohort_2",
            groups=[{"properties": [{"key": "key_2", "value": "value_2", "type": "person"}]}],
        )

        cohort1.calculate_people()
        cohort1.calculate_people_ch()

        cohort2.calculate_people()
        cohort2.calculate_people_ch()

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            with freeze_time("2020-01-04T13:01:01Z"):
                res = ClickhouseTrends().run(
                    Filter(
                        data={
                            "date_from": "-7d",
                            "events": [{"id": "$pageview"}],
                            "properties": [],
                            "breakdown": [cohort1.pk, cohort2.pk],
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )

        self.assertEqual(res[0]["count"], 1)
        self.assertEqual(res[1]["count"], 2)

    @test_with_materialized_columns(person_properties=["key", "key_2"], verify_no_jsonextract=False)
    def test_breakdown_single_cohort(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "value"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"key_2": "value_2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        p3 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p3"], properties={"key_2": "value_2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        cohort1 = _create_cohort(
            team=self.team,
            name="cohort_1",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )

        cohort1.calculate_people()
        cohort1.calculate_people_ch()

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            with freeze_time("2020-01-04T13:01:01Z"):
                res = ClickhouseTrends().run(
                    Filter(
                        data={
                            "date_from": "-7d",
                            "events": [{"id": "$pageview"}],
                            "properties": [],
                            "breakdown": cohort1.pk,
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )

        self.assertEqual(res[0]["count"], 1)

    @test_with_materialized_columns(["key", "$current_url"])
    def test_filtering_with_action_props(self):
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "val", "$current_url": "/some/page"},
        )
        _create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"key": "val", "$current_url": "/some/page"},
        )
        _create_event(
            event="sign up",
            distinct_id="person3",
            team=self.team,
            properties={"key": "val", "$current_url": "/another/page"},
        )

        action = Action.objects.create(name="sign up", team=self.team)
        ActionStep.objects.create(
            action=action,
            event="sign up",
            url="/some/page",
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        response = ClickhouseTrends().run(
            Filter(data={"date_from": "-14d", "actions": [{"id": action.pk, "type": "actions", "order": 0}],}),
            self.team,
        )

        self.assertEqual(response[0]["count"], 2)

    def test_trends_math_without_math_property(self):
        with self.assertRaises(ValidationError):
            ClickhouseTrends().run(
                Filter(data={"events": [{"id": "sign up", "math": "sum"}]}), self.team,
            )

    @snapshot_clickhouse_queries
    def test_filtering_with_group_props(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})
        _create_event(
            event="$pageview", distinct_id="person1", team=self.team, timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )

        filter = Filter(
            {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "properties": [
                    {"key": "industry", "value": "finance", "type": "group", "group_type_index": 0},
                    {"key": "key", "value": "value", "type": "person"},
                ],
            },
            team=self.team,
        )

        response = ClickhouseTrends().run(filter, self.team)
        self.assertEqual(response[0]["count"], 1)

    @snapshot_clickhouse_queries
    def test_aggregating_by_group(self):
        self._create_groups()

        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:6", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )

        filter = Filter(
            {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "math": "unique_group",
                        "math_group_type_index": 0,
                    }
                ],
            },
            team=self.team,
        )

        response = ClickhouseTrends().run(filter, self.team)
        self.assertEqual(response[0]["count"], 2)

        filter = Filter(
            {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "math": "unique_group",
                        "math_group_type_index": 1,
                    }
                ],
            },
            team=self.team,
        )
        response = ClickhouseTrends().run(filter, self.team)
        self.assertEqual(response[0]["count"], 1)
