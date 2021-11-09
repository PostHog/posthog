from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.group import create_group
from ee.clickhouse.queries.breakdown_props import get_breakdown_prop_values
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.person import Person
from posthog.test.base import APIBaseTest, test_with_materialized_columns


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestBreakdownProps(ClickhouseTestMixin, APIBaseTest):
    @test_with_materialized_columns(event_properties=["$host", "distinct_id"], person_properties=["$browser", "email"])
    @snapshot_clickhouse_queries
    def test_breakdown_person_props(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"$browser": "test"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        self.team.test_account_filters = [
            {"key": "email", "type": "person", "value": "posthog.com", "operator": "not_icontains"},
            {
                "key": "$host",
                "type": "event",
                "value": ["127.0.0.1:3000", "127.0.0.1:5000", "localhost:5000", "localhost:8000"],
                "operator": "is_not",
            },
            {"key": "distinct_id", "type": "event", "value": "posthog.com", "operator": "not_icontains"},
        ]
        self.team.save()
        with freeze_time("2020-01-04T13:01:01Z"):
            filter = Filter(
                data={
                    "insight": "FUNNELS",
                    "properties": [],
                    "filter_test_accounts": True,
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                    "actions": [],
                    "funnel_viz_type": "steps",
                    "display": "FunnelViz",
                    "interval": "day",
                    "breakdown": "$browser",
                    "breakdown_type": "person",
                    "date_from": "-14d",
                    "funnel_window_days": 14,
                }
            )
            res = get_breakdown_prop_values(
                filter, Entity({"id": "$pageview", "type": "events"}), "count(*)", self.team.pk, 5
            )
            self.assertEqual(res, ["test"])

    def test_breakdown_person_props_with_entity_filter(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"$browser": "test"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"$browser": "test2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2020-01-02T12:00:00Z",
            properties={"key": "val"},
        )

        cohort = Cohort.objects.create(team=self.team, name="a", groups=[{"properties": {"$browser": "test"}}])
        cohort.calculate_people()
        cohort.calculate_people_ch()

        entity_params = [
            {
                "id": "$pageview",
                "name": "$pageview",
                "type": "events",
                "order": 0,
                "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
            }
        ]
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            with freeze_time("2020-01-04T13:01:01Z"):
                filter = Filter(
                    data={
                        "insight": "FUNNELS",
                        "properties": [],
                        "filter_test_accounts": False,
                        "events": entity_params,
                        "actions": [],
                        "funnel_viz_type": "steps",
                        "display": "FunnelViz",
                        "interval": "day",
                        "breakdown": "$browser",
                        "breakdown_type": "person",
                        "date_from": "-14d",
                        "funnel_window_days": 14,
                    }
                )
                res = get_breakdown_prop_values(filter, Entity(entity_params[0]), "count(*)", self.team.pk, 5)
                self.assertEqual(res, ["test"])

    @snapshot_clickhouse_queries
    def test_breakdown_group_props(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:7", properties={"industry": "finance"})
        create_group(
            team_id=self.team.pk, group_type_index=0, group_key="org:8", properties={"industry": "another", "out": 1}
        )
        create_group(
            team_id=self.team.pk, group_type_index=1, group_key="company:10", properties={"industry": "foobar"}
        )
        # :TRICKY: Test group type overlapping
        create_group(team_id=self.team.pk, group_type_index=1, group_key="org:8", properties={"industry": "foobar"})

        for org_index in range(5, 9):
            _create_event(
                event="$pageview",
                distinct_id="person1",
                team=self.team,
                properties={"$group_0": f"org:{org_index}"},
                timestamp="2020-01-02T12:00:00Z",
            )

        filter = Filter(
            data={
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "events": [{"id": "$pageview", "type": "events", "order": 0,}],
                "properties": [
                    {"key": "out", "value": "", "type": "group", "group_type_index": 0, "operator": "is_not_set"}
                ],
            },
            team=self.team,
        )
        result = get_breakdown_prop_values(filter, filter.entities[0], "count(*)", self.team.pk, 5)
        self.assertEqual(result, ["finance", "technology"])
