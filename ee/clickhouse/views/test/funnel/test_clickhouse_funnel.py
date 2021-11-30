import json
from datetime import datetime

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.models.group import create_group
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from ee.clickhouse.views.test.funnel.util import EventPattern, FunnelRequest, get_funnel_actors_ok, get_funnel_ok
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.test.base import APIBaseTest


class ClickhouseTestFunnelGroups(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def _create_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})

        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:1", properties={})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:2", properties={})

    @snapshot_clickhouse_queries
    def test_funnel_aggregation_with_groups(self):
        self._create_groups()

        events_by_person = {
            "user_1": [
                {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14), "properties": {"$group_0": "org:5"}},
                {
                    "event": "user signed up",  # same person, different group, so should count as different step 1 in funnel
                    "timestamp": datetime(2020, 1, 10, 14),
                    "properties": {"$group_0": "org:6"},
                },
            ],
            "user_2": [
                {  # different person, same group, so should count as step two in funnel
                    "event": "paid",
                    "timestamp": datetime(2020, 1, 3, 14),
                    "properties": {"$group_0": "org:5"},
                },
            ],
        }
        created_people = journeys_for(events_by_person, self.team)

        params = FunnelRequest(
            events=json.dumps(
                [
                    EventPattern(id="user signed up", type="events", order=0),
                    EventPattern(id="paid", type="events", order=1),
                ]
            ),
            date_from="2020-01-01",
            date_to="2020-01-14",
            aggregation_group_type_index=0,
            insight=INSIGHT_FUNNELS,
        )

        result = get_funnel_ok(self.client, self.team.pk, params)

        assert result["user signed up"]["count"] == 2
        assert result["paid"]["count"] == 1
        assert result["paid"]["average_conversion_time"] == 86400

        actors = get_funnel_actors_ok(self.client, result["user signed up"]["converted_people_url"])
        actor_ids = [str(val["id"]) for val in actors]
        assert actor_ids == ["org:5", "org:6"]

    @snapshot_clickhouse_queries
    def test_funnel_group_aggregation_with_groups_entity_filtering(self):
        self._create_groups()

        events_by_person = {
            "user_1": [
                {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14), "properties": {"$group_0": "org:5"}}
            ],
            "user_2": [
                {  # different person, same group, so should count as step two in funnel
                    "event": "paid",
                    "timestamp": datetime(2020, 1, 3, 14),
                    "properties": {"$group_0": "org:5"},
                },
            ],
            "user_3": [
                {  # different person, different group, so should be discarded from step 1 in funnel
                    "event": "user signed up",
                    "timestamp": datetime(2020, 1, 10, 14),
                    "properties": {"$group_0": "org:6"},
                },
            ],
        }
        created_people = journeys_for(events_by_person, self.team)

        params = FunnelRequest(
            events=json.dumps(
                [
                    EventPattern(id="user signed up", type="events", order=0, properties={"$group_0": "org:5"}),
                    EventPattern(id="paid", type="events", order=1),
                ]
            ),
            date_from="2020-01-01",
            date_to="2020-01-14",
            aggregation_group_type_index=0,
            insight=INSIGHT_FUNNELS,
        )

        result = get_funnel_ok(self.client, self.team.pk, params)

        assert result["user signed up"]["count"] == 1
        assert result["paid"]["count"] == 1
        assert result["paid"]["average_conversion_time"] == 86400

        actors = get_funnel_actors_ok(self.client, result["user signed up"]["converted_people_url"])
        actor_ids = [str(val["id"]) for val in actors]
        assert actor_ids == ["org:5"]

    @snapshot_clickhouse_queries
    def test_funnel_with_groups_entity_filtering(self):
        self._create_groups()

        events_by_person = {
            "user_1": [
                {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14), "properties": {"$group_0": "org:5"}},
                {
                    "event": "paid",
                    "timestamp": datetime(2020, 1, 3, 14),
                    "properties": {
                        "$group_0": "org:6"
                    },  # different group, but doesn't matter since not aggregating by groups
                },
                {
                    "event": "user signed up",  # event belongs to different group, so shouldn't enter funnel
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$group_0": "org:6"},
                },
                {
                    "event": "paid",
                    "timestamp": datetime(2020, 1, 3, 14),
                    "properties": {"$group_0": "org:6"},  # event belongs to different group, so shouldn't enter funnel
                },
            ],
        }
        created_people = journeys_for(events_by_person, self.team)

        params = FunnelRequest(
            events=json.dumps(
                [
                    EventPattern(id="user signed up", type="events", order=0, properties={"$group_0": "org:5"}),
                    EventPattern(id="paid", type="events", order=1),
                ]
            ),
            date_from="2020-01-01",
            date_to="2020-01-14",
            insight=INSIGHT_FUNNELS,
        )

        result = get_funnel_ok(self.client, self.team.pk, params)

        assert result["user signed up"]["count"] == 1
        assert result["paid"]["count"] == 1
        assert result["paid"]["average_conversion_time"] == 86400

        actors = get_funnel_actors_ok(self.client, result["user signed up"]["converted_people_url"])
        actor_ids = [str(val["id"]) for val in actors]

        assert actor_ids == sorted([str(created_people["user_1"].uuid)])

    @snapshot_clickhouse_queries
    def test_funnel_with_groups_global_filtering(self):
        self._create_groups()

        events_by_person = {
            "user_1": [
                {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14), "properties": {"$group_0": "org:5"}},
                {
                    "event": "paid",
                    "timestamp": datetime(2020, 1, 3, 14),
                    "properties": {
                        "$group_0": "org:6"
                    },  # second event belongs to different group, so shouldn't complete funnel
                },
            ],
            "user_2": [
                {
                    "event": "user signed up",  # event belongs to different group, so shouldn't enter funnel
                    "timestamp": datetime(2020, 1, 2, 14),
                    "properties": {"$group_0": "org:6"},
                },
                {
                    "event": "paid",
                    "timestamp": datetime(2020, 1, 3, 14),
                    "properties": {"$group_0": "org:5"},  # same group, but different person, so not in funnel
                },
            ],
        }
        created_people = journeys_for(events_by_person, self.team)

        params = FunnelRequest(
            events=json.dumps(
                [
                    EventPattern(id="user signed up", type="events", order=0),
                    EventPattern(id="paid", type="events", order=1),
                ]
            ),
            date_from="2020-01-01",
            date_to="2020-01-14",
            insight=INSIGHT_FUNNELS,
            properties=json.dumps([{"key": "industry", "value": "finance", "type": "group", "group_type_index": 0}]),
        )

        result = get_funnel_ok(self.client, self.team.pk, params)

        assert result["user signed up"]["count"] == 1
        assert result["paid"]["count"] == 0

        actors = get_funnel_actors_ok(self.client, result["user signed up"]["converted_people_url"])
        actor_ids = [str(val["id"]) for val in actors]

        assert actor_ids == sorted([str(created_people["user_1"].uuid)])

    # TODO: move all tests
