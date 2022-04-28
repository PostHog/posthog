from freezegun import freeze_time

from ee.clickhouse.materialized_columns import materialize
from ee.clickhouse.models.group import create_group
from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.client import sync_execute
from posthog.models import Action, ActionStep
from posthog.models.cohort import Cohort
from posthog.models.element import Element
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person
from posthog.test.base import APIBaseTest, _create_event, _create_person


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    is_static = kwargs.pop("is_static", False)
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, is_static=is_static)
    return cohort


class TestEventQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self._create_sample_data()

    def _create_sample_data(self):
        distinct_id = "user_one_{}".format(self.team.pk)
        _create_person(distinct_ids=[distinct_id], team=self.team)

        _create_event(event="viewed", distinct_id=distinct_id, team=self.team, timestamp="2021-05-01 00:00:00")

    def _run_query(self, filter: Filter, entity=None):
        entity = entity or filter.entities[0]

        query, params = TrendsEventQuery(filter=filter, entity=entity, team=self.team).get_query()

        result = sync_execute(query, params)

        return result, query

    @snapshot_clickhouse_queries
    def test_basic_event_filter(self):
        self._run_query(
            Filter(
                data={
                    "date_from": "2021-05-01 00:00:00",
                    "date_to": "2021-05-07 00:00:00",
                    "events": [{"id": "viewed", "order": 0},],
                }
            )
        )

    def test_person_properties_filter(self):
        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
                "properties": [
                    {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
                    {"key": "key", "value": "val"},
                ],
            }
        )

        entity = Entity({"id": "viewed", "type": "events"})

        self._run_query(filter, entity)

        entity = Entity(
            {
                "id": "viewed",
                "type": "events",
                "properties": [
                    {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
                    {"key": "key", "value": "val"},
                ],
            }
        )

        filter = Filter(
            data={"date_from": "2021-05-01 00:00:00", "date_to": "2021-05-07 00:00:00", "events": [entity.to_dict()],}
        )

        self._run_query(filter, entity)

    @snapshot_clickhouse_queries
    def test_event_properties_filter(self):
        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
                "properties": [{"key": "some_key", "value": "test_val", "operator": "exact", "type": "event"}],
            }
        )

        entity = Entity({"id": "viewed", "type": "events"})

        self._run_query(filter, entity)

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
            }
        )

        entity = Entity(
            {
                "id": "viewed",
                "type": "events",
                "properties": [{"key": "some_key", "value": "test_val", "operator": "exact", "type": "event"}],
            }
        )

        self._run_query(filter, entity)

    # just smoke test making sure query runs because no new functions are used here
    @snapshot_clickhouse_queries
    def test_cohort_filter(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
                "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
            }
        )

        self._run_query(filter)

    # just smoke test making sure query runs because no new functions are used here
    @snapshot_clickhouse_queries
    def test_entity_filtered_by_cohort(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [
                    {
                        "id": "$pageview",
                        "order": 0,
                        "properties": [{"key": "id", "type": "cohort", "value": cohort.pk}],
                    },
                ],
            }
        )

        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "test"})
        _create_event(team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-02T12:00:00Z")

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "foo"})
        _create_event(team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-02T12:01:00Z")

        self._run_query(filter)

    # smoke test make sure query is formatted and runs
    @snapshot_clickhouse_queries
    def test_static_cohort_filter(self):
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[], is_static=True)

        filter = Filter(
            data={
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-07 00:00:00",
                "events": [{"id": "viewed", "order": 0},],
                "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
            },
            team=self.team,
        )

        self._run_query(filter)

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21")
    def test_account_filters(self):
        person1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
        person2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

        _create_event(event="event_name", team=self.team, distinct_id="person_1")
        _create_event(event="event_name", team=self.team, distinct_id="person_2")
        _create_event(event="event_name", team=self.team, distinct_id="person_2")

        cohort = Cohort.objects.create(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        self.team.test_account_filters = [{"key": "id", "value": cohort.pk, "type": "cohort"}]
        self.team.save()

        filter = Filter(
            data={"events": [{"id": "event_name", "order": 0},], "filter_test_accounts": True}, team=self.team
        )

        self._run_query(filter)

    def test_action_with_person_property_filter(self):
        person1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
        person2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

        _create_event(event="event_name", team=self.team, distinct_id="person_1")
        _create_event(event="event_name", team=self.team, distinct_id="person_2")
        _create_event(event="event_name", team=self.team, distinct_id="person_2")

        action = Action.objects.create(team=self.team, name="action1")
        ActionStep.objects.create(
            event="event_name", action=action, properties=[{"key": "name", "type": "person", "value": "John"}],
        )

        filter = Filter(data={"actions": [{"id": action.id, "type": "actions", "order": 0},]})

        self._run_query(filter)

    @snapshot_clickhouse_queries
    def test_denormalised_props(self):
        filters = {
            "events": [
                {
                    "id": "user signed up",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": "test_prop", "value": "hi"}],
                },
            ],
            "date_from": "2020-01-01",
            "properties": [{"key": "test_prop", "value": "hi"}],
            "date_to": "2020-01-14",
        }

        materialize("events", "test_prop")

        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "value"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"test_prop": "hi"},
        )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"key_2": "value_2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"test_prop": "hi"},
        )

        filter = Filter(data=filters)
        _, query = self._run_query(filter)
        self.assertIn("mat_test_prop", query)

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-21")
    def test_element(self):
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_other_val"},
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=["small"],
                    text="bla bla",
                    attributes={},
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(tag_name="button", attr_class=["btn", "btn-primary"], nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="label", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_val"},
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=["small"],
                    text="bla bla",
                    attributes={},
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(tag_name="button", attr_class=["btn", "btn-secondary"], nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="img", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
        )

        filter = Filter(
            data={
                "events": [{"id": "event_name", "order": 0},],
                "properties": [{"key": "tag_name", "value": ["label"], "operator": "exact", "type": "element"}],
            }
        )

        self._run_query(filter)

        self._run_query(
            filter.with_data(
                {"properties": [{"key": "tag_name", "value": [], "operator": "exact", "type": "element"}],}
            )
        )

    def _create_groups_test_data(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:1", properties={"another": "value"})

        Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"$browser": "test"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"$browser": "foobar"})
        Person.objects.create(team_id=self.team.pk, distinct_ids=["p3"], properties={"$browser": "test"})

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"$group_0": "org:5", "$group_1": "company:1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"$group_0": "org:6", "$group_1": "company:1"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"$group_0": "org:6"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp="2020-01-02T12:00:00Z",
            properties={"$group_0": "org:5"},
        )

    @snapshot_clickhouse_queries
    def test_groups_filters(self):
        self._create_groups_test_data()

        filter = Filter(
            {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "properties": [
                    {"key": "industry", "value": "finance", "type": "group", "group_type_index": 0},
                    {"key": "another", "value": "value", "type": "group", "group_type_index": 1},
                ],
            },
            team=self.team,
        )

        results, _ = self._run_query(filter)
        self.assertEqual(len(results), 1)

    @snapshot_clickhouse_queries
    def test_groups_filters_mixed(self):
        self._create_groups_test_data()

        filter = Filter(
            {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "properties": [
                    {"key": "industry", "value": "finance", "type": "group", "group_type_index": 0},
                    {"key": "$browser", "value": "test", "type": "person"},
                ],
            },
            team=self.team,
        )

        results, _ = self._run_query(filter)
        self.assertEqual(len(results), 2)
