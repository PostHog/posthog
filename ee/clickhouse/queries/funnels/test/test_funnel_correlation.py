from uuid import uuid4

from rest_framework.exceptions import ValidationError

from ee.clickhouse.materialized_columns import materialize
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelPersons
from ee.clickhouse.queries.funnels.test.breakdown_cases import funnel_breakdown_test_factory
from ee.clickhouse.queries.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models import Element
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.queries.test.test_funnel import funnel_test_factory
from posthog.test.base import APIBaseTest, test_with_materialized_columns

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name, properties=properties)
    return action


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseFunnelCorrelation(ClickhouseTestMixin, APIBaseTest):  # type: ignore

    maxDiff = None

    def test_basic_funnel_correlation_with_events(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        result = correlation.run()["events"]

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [6, 1 / 6]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related",
                    "success_count": 6,
                    "failure_count": 1,
                    # "odds_ratio": 6.0,
                    "correlation_type": "success",
                },
                {
                    "event": "negatively_related",
                    "success_count": 1,
                    "failure_count": 6,
                    # "odds_ratio": 1 / 6,
                    "correlation_type": "failure",
                },
            ],
        )

    def test_basic_funnel_correlation_with_properties(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "properties",
            "funnel_correlation_value": "$browser",
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Positive"})
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Negative"})
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        result = correlation.run()["events"]

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [11, 1 / 11]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "Positive",
                    "success_count": 11,
                    "failure_count": 1,
                    # "odds_ratio": 11.0,
                    "correlation_type": "success",
                },
                {
                    "event": "Negative",
                    "success_count": 1,
                    "failure_count": 11,
                    # "odds_ratio": 1 / 11,
                    "correlation_type": "failure",
                },
            ],
        )
