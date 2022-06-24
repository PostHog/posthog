from datetime import datetime

from ee.clickhouse.queries.funnels.test.breakdown_cases import funnel_breakdown_group_test_factory
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.queries.funnels.funnel import ClickhouseFunnel
from posthog.queries.funnels.funnel_persons import ClickhouseFunnelActors
from posthog.queries.funnels.test.breakdown_cases import funnel_breakdown_test_factory
from posthog.queries.funnels.test.test_funnel import _create_action, funnel_test_factory
from posthog.test.base import ClickhouseTestMixin, _create_event, _create_person
from posthog.test.test_journeys import journeys_for


class TestFunnelBreakdown(ClickhouseTestMixin, funnel_breakdown_test_factory(ClickhouseFunnel, ClickhouseFunnelActors, _create_event, _create_action, _create_person), funnel_breakdown_group_test_factory(ClickhouseFunnel, ClickhouseFunnelActors, _create_event, _create_action, _create_person)):  # type: ignore
    maxDiff = None


class TestClickhouseFunnel(funnel_test_factory(ClickhouseFunnel, _create_event, _create_person)):  # type: ignore
    maxDiff = None

    def test_funnel_aggregation_with_groups_with_cohort_filtering(self):

        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)

        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})

        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:1", properties={})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:2", properties={})

        _create_person(distinct_ids=[f"user_1"], team=self.team, properties={"email": "fake@test.com"})
        _create_person(distinct_ids=[f"user_2"], team=self.team, properties={"email": "fake@test.com"})
        _create_person(distinct_ids=[f"user_3"], team=self.team, properties={"email": "fake_2@test.com"})

        action1 = Action.objects.create(team=self.team, name="action1")
        ActionStep.objects.create(
            event="$pageview", action=action1,
        )

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {"properties": [{"key": "email", "operator": "icontains", "value": "fake@test.com", "type": "person"}]}
            ],
        )

        events_by_person = {
            "user_1": [
                {"event": "$pageview", "timestamp": datetime(2020, 1, 2, 14), "properties": {"$group_0": "org:5"}},
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
            "user_3": [
                {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14), "properties": {"$group_0": "org:7"}},
                {  # person not in cohort so should be filtered out
                    "event": "paid",
                    "timestamp": datetime(2020, 1, 3, 14),
                    "properties": {"$group_0": "org:7"},
                },
            ],
        }
        created_people = journeys_for(events_by_person, self.team)
        cohort.calculate_people_ch(pending_version=0)

        filters = {
            "events": [
                {
                    "id": "user signed up",
                    "type": "events",
                    "order": 0,
                    "properties": [{"type": "precalculated-cohort", "key": "id", "value": cohort.pk}],
                },
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "aggregation_group_type_index": 0,
        }

        filter = Filter(data=filters)
        funnel = ClickhouseFunnel(filter, self.team)
        result = funnel.run()

        self.assertEqual(result[0]["name"], "user signed up")
        self.assertEqual(result[0]["count"], 2)

        self.assertEqual(result[1]["name"], "paid")
        self.assertEqual(result[1]["count"], 1)
