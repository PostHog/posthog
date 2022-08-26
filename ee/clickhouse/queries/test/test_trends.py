from datetime import datetime

from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.instance_setting import override_instance_config
from posthog.models.person import Person
from posthog.queries.test.test_trends import trend_test_factory
from posthog.queries.trends.person import TrendsActors
from posthog.queries.trends.trends import Trends
from posthog.test.base import _create_event, snapshot_clickhouse_queries, test_with_materialized_columns
from posthog.test.test_journeys import journeys_for


# override tests from test factory if intervals are different
class TestClickhouseTrends(trend_test_factory(Trends)):  # type: ignore
    maxDiff = None

    def _get_trend_people(self, filter, entity):
        _, serialized_actors = TrendsActors(filter=filter, entity=entity, team=self.team).get_actors()
        return serialized_actors

    def _create_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:7", properties={"industry": "finance"})
        create_group(
            team_id=self.team.pk, group_type_index=1, group_key="company:10", properties={"industry": "finance"}
        )

    # TODO: Delete this test when moved to person-on-events
    def test_breakdown_with_filter_groups(self):
        self._create_groups()

        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "oh", "$group_0": "org:7", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:5"},
            timestamp="2020-01-02T12:00:01Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:6"},
            timestamp="2020-01-02T12:00:02Z",
        )

        response = Trends().run(
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

    @test_with_materialized_columns(event_properties=["key"], group_properties=[(0, "industry")])
    @snapshot_clickhouse_queries
    def test_breakdown_with_filter_groups_person_on_events(self):
        self._create_groups()

        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "oh", "$group_0": "org:7", "$group_1": "company:10"},
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:5"},
            timestamp="2020-01-02T12:00:01Z",
        )
        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"key": "uh", "$group_0": "org:6"},
            timestamp="2020-01-02T12:00:02Z",
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = Trends().run(
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

    # TODO: Delete this test when moved to person-on-events
    def test_breakdown_by_group_props(self):
        self._create_groups()

        journey = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:5"},
                    "group0_properties": {"industry": "finance"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$group_0": "org:6"},
                    "group0_properties": {"industry": "technology"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$group_0": "org:7", "$group_1": "company:10"},
                    "group0_properties": {"industry": "finance"},
                    "group1_properties": {"industry": "finance"},
                },
            ],
        }

        journeys_for(events_by_person=journey, team=self.team)

        filter = Filter(
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
            }
        )
        response = Trends().run(filter, self.team,)

        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]["breakdown_value"], "finance")
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[1]["breakdown_value"], "technology")
        self.assertEqual(response[1]["count"], 1)

        filter = filter.with_data(
            {"breakdown_value": "technology", "date_from": "2020-01-02T00:00:00Z", "date_to": "2020-01-03"}
        )
        entity = Entity({"id": "sign up", "name": "sign up", "type": "events", "order": 0,})
        res = self._get_trend_people(filter, entity)

        self.assertEqual(res[0]["distinct_ids"], ["person1"])

    @test_with_materialized_columns(group_properties=[(0, "industry")])
    @snapshot_clickhouse_queries
    def test_breakdown_by_group_props_person_on_events(self):
        self._create_groups()

        journey = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:5"},
                    "group0_properties": {"industry": "finance"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 13),
                    "properties": {"$group_0": "org:6"},
                    "group0_properties": {"industry": "technology"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 15),
                    "properties": {"$group_0": "org:7", "$group_1": "company:10"},
                    "group0_properties": {"industry": "finance"},
                    "group1_properties": {"industry": "finance"},
                },
            ],
        }

        journeys_for(events_by_person=journey, team=self.team)

        filter = Filter(
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
            }
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = Trends().run(filter, self.team,)

            self.assertEqual(len(response), 2)
            self.assertEqual(response[0]["breakdown_value"], "finance")
            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[1]["breakdown_value"], "technology")
            self.assertEqual(response[1]["count"], 1)

            filter = filter.with_data(
                {"breakdown_value": "technology", "date_from": "2020-01-02T00:00:00Z", "date_to": "2020-01-03"}
            )
            entity = Entity({"id": "sign up", "name": "sign up", "type": "events", "order": 0,})
            res = self._get_trend_people(filter, entity)

            self.assertEqual(res[0]["distinct_ids"], ["person1"])

    # TODO: Delete this test when moved to person-on-events
    def test_breakdown_by_group_props_with_person_filter(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})

        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
            person_properties={"key": "value"},
            group0_properties={"industry": "finance"},
        )
        _create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
            person_properties={},
            group0_properties={"industry": "technology"},
        )

        filter = Filter(
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                "properties": [{"key": "key", "value": "value", "type": "person"}],
            }
        )

        response = Trends().run(filter, self.team,)

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["breakdown_value"], "finance")
        self.assertEqual(response[0]["count"], 1)

    # TODO: Delete this test when moved to person-on-events
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

        response = Trends().run(filter, self.team)
        self.assertEqual(response[0]["count"], 1)

    @test_with_materialized_columns(person_properties=["key"], group_properties=[(0, "industry")])
    @snapshot_clickhouse_queries
    def test_breakdown_by_group_props_with_person_filter_person_on_events(self):
        self._create_groups()

        Person.objects.create(team_id=self.team.pk, distinct_ids=["person1"], properties={"key": "value"})

        _create_event(
            event="sign up",
            distinct_id="person1",
            team=self.team,
            properties={"$group_0": "org:5"},
            timestamp="2020-01-02T12:00:00Z",
            person_properties={"key": "value"},
            group0_properties={"industry": "finance"},
        )
        _create_event(
            event="sign up",
            distinct_id="person2",
            team=self.team,
            properties={"$group_0": "org:6"},
            timestamp="2020-01-02T12:00:00Z",
            person_properties={},
            group0_properties={"industry": "technology"},
        )

        filter = Filter(
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                "properties": [{"key": "key", "value": "value", "type": "person"}],
            }
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = Trends().run(filter, self.team,)

            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["breakdown_value"], "finance")
            self.assertEqual(response[0]["count"], 1)

    @test_with_materialized_columns(person_properties=["key"], group_properties=[(0, "industry")])
    @snapshot_clickhouse_queries
    def test_filtering_with_group_props_person_on_events(self):
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

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = Trends().run(filter, self.team)
            self.assertEqual(response[0]["count"], 1)

    @test_with_materialized_columns(group_properties=[(0, "industry"), (2, "name")])
    @snapshot_clickhouse_queries
    def test_filtering_by_multiple_groups_person_on_events(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=2)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=2, group_key="company:5", properties={"name": "five"})
        create_group(team_id=self.team.pk, group_type_index=2, group_key="company:6", properties={"name": "six"})

        journey = {
            "person1": [
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 12),
                    "properties": {"$group_0": "org:5", "$group_2": "company:6"},
                },
                {
                    "event": "sign up",
                    "timestamp": datetime(2020, 1, 2, 12, 30),
                    "properties": {"$group_2": "company:6"},
                },
                {"event": "sign up", "timestamp": datetime(2020, 1, 2, 13), "properties": {"$group_0": "org:6"},},
                {"event": "sign up", "timestamp": datetime(2020, 1, 3, 15), "properties": {"$group_2": "company:5"},},
            ],
        }

        journeys_for(events_by_person=journey, team=self.team)

        filter = Filter(
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12",
                "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                "properties": [
                    {"key": "industry", "value": "finance", "type": "group", "group_type_index": 0},
                    {"key": "name", "value": "six", "type": "group", "group_type_index": 2},
                ],
            }
        )

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            response = Trends().run(filter, self.team,)

            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["count"], 1)
            self.assertEqual(response[0]["data"], [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

            filter = filter.with_data({"date_from": "2020-01-02T00:00:00Z", "date_to": "2020-01-02T00:00:00Z"})
            entity = Entity({"id": "sign up", "name": "sign up", "type": "events", "order": 0,})
            res = self._get_trend_people(filter, entity)

            self.assertEqual(res[0]["distinct_ids"], ["person1"])
