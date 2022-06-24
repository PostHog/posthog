from datetime import datetime

from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters import Filter
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.queries.funnels.test.breakdown_cases import FunnelStepResult, assert_funnel_breakdown_result_is_correct
from posthog.test.base import APIBaseTest, snapshot_clickhouse_queries
from posthog.test.test_journeys import journeys_for


def funnel_breakdown_group_test_factory(Funnel, FunnelPerson, _create_event, _create_action, _create_person):
    class TestFunnelBreakdownGroup(APIBaseTest):
        def _get_actor_ids_at_step(self, filter, funnel_step, breakdown_value=None):
            person_filter = filter.with_data({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
            _, serialized_result = FunnelPerson(person_filter, self.team).get_actors()

            return [val["id"] for val in serialized_result]

        def _create_groups(self):
            GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
            GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

            create_group(
                team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"}
            )
            create_group(
                team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"}
            )
            create_group(team_id=self.team.pk, group_type_index=1, group_key="org:5", properties={"industry": "random"})

        @snapshot_clickhouse_queries
        def test_funnel_breakdown_group(self):
            self._create_groups()

            people = journeys_for(
                {
                    "person1": [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 1, 12),
                            "properties": {"$group_0": "org:5", "$browser": "Chrome"},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 1, 13),
                            "properties": {"$group_0": "org:5", "$browser": "Chrome"},
                        },
                        {
                            "event": "buy",
                            "timestamp": datetime(2020, 1, 1, 15),
                            "properties": {"$group_0": "org:5", "$browser": "Chrome"},
                        },
                    ],
                    "person2": [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 2, 14),
                            "properties": {"$group_0": "org:6", "$browser": "Safari"},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 2, 16),
                            "properties": {"$group_0": "org:6", "$browser": "Safari"},
                        },
                    ],
                    "person3": [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 2, 14),
                            "properties": {"$group_0": "org:6", "$browser": "Safari"},
                        },
                    ],
                },
                self.team,
            )

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
            }

            filter = Filter(data=filters, team=self.team)
            result = Funnel(filter, self.team).run()

            assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown="finance", count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown="finance",
                        count=1,
                        average_conversion_time=3600.0,
                        median_conversion_time=3600.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown="finance",
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                ],
            )

            # Querying persons when aggregating by persons should be ok, despite group breakdown
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "finance"), [people["person1"].uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, "finance"), [people["person1"].uuid])

            assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown="technology", count=2),
                    FunnelStepResult(
                        name="play movie",
                        breakdown="technology",
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                    FunnelStepResult(name="buy", breakdown="technology", count=0),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "technology"), [people["person2"].uuid, people["person3"].uuid]
            )
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, "technology"), [people["person2"].uuid])

        @snapshot_clickhouse_queries
        def test_funnel_aggregate_by_groups_breakdown_group(self):
            self._create_groups()

            journeys_for(
                {
                    "person1": [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 1, 12),
                            "properties": {"$group_0": "org:5", "$browser": "Chrome"},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 1, 13),
                            "properties": {"$group_0": "org:5", "$browser": "Chrome"},
                        },
                        {
                            "event": "buy",
                            "timestamp": datetime(2020, 1, 1, 15),
                            "properties": {"$group_0": "org:5", "$browser": "Chrome"},
                        },
                    ],
                    "person2": [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 2, 14),
                            "properties": {"$group_0": "org:6", "$browser": "Safari"},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 2, 16),
                            "properties": {"$group_0": "org:6", "$browser": "Safari"},
                        },
                    ],
                    "person3": [
                        {
                            "event": "buy",
                            "timestamp": datetime(2020, 1, 2, 18),
                            "properties": {"$group_0": "org:6", "$browser": "Safari"},
                        },
                    ],
                },
                self.team,
            )

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown": "industry",
                "breakdown_type": "group",
                "breakdown_group_type_index": 0,
                "aggregation_group_type_index": 0,
            }

            result = Funnel(Filter(data=filters, team=self.team), self.team).run()

            assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown="finance", count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown="finance",
                        count=1,
                        average_conversion_time=3600.0,
                        median_conversion_time=3600.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown="finance",
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                ],
            )

            assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown="technology", count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown="technology",
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown="technology",
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                ],
            )

    return TestFunnelBreakdownGroup
