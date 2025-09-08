from typing import Any, cast

import unittest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    also_test_with_person_on_events_v2,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest import skip

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    EventPropertyFilter,
    EventsNode,
    FunnelCorrelationQuery,
    FunnelCorrelationResultsType,
    FunnelsActorsQuery,
    FunnelsQuery,
    GroupPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
)

from posthog.constants import INSIGHT_FUNNELS
from posthog.hogql_queries.insights.funnels.funnel_correlation_query_runner import (
    EventContingencyTable,
    EventStats,
    FunnelCorrelationQueryRunner,
)
from posthog.hogql_queries.insights.funnels.test.test_funnel_correlation_actors import get_actors
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models.action import Action
from posthog.models.element import Element
from posthog.models.group.util import create_group
from posthog.models.instance_setting import override_instance_config
from posthog.test.test_journeys import journeys_for
from posthog.test.test_utils import create_group_type_mapping_without_created_at


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name, "properties": properties}])
    return action


class BaseTestClickhouseFunnelCorrelation(ClickhouseTestMixin, APIBaseTest):
    __test__ = False
    maxDiff = None

    def _get_events_for_filters(
        self,
        filters,
        funnelCorrelationType=FunnelCorrelationResultsType.EVENTS,
        funnelCorrelationNames=None,
        funnelCorrelationExcludeNames=None,
        funnelCorrelationExcludeEventNames=None,
        funnelCorrelationEventNames=None,
        funnelCorrelationEventExcludePropertyNames=None,
    ):
        funnels_query = cast(FunnelsQuery, filter_to_query(filters))
        actors_query = FunnelsActorsQuery(source=funnels_query)
        correlation_query = FunnelCorrelationQuery(
            source=actors_query,
            funnelCorrelationType=funnelCorrelationType,
            funnelCorrelationNames=funnelCorrelationNames,
            funnelCorrelationExcludeNames=funnelCorrelationExcludeNames,
            funnelCorrelationExcludeEventNames=funnelCorrelationExcludeEventNames,
            funnelCorrelationEventNames=funnelCorrelationEventNames,
            funnelCorrelationEventExcludePropertyNames=funnelCorrelationEventExcludePropertyNames,
        )
        result, skewed_totals, _, _ = FunnelCorrelationQueryRunner(
            query=correlation_query, team=self.team
        )._calculate_internal()
        return result, skewed_totals

    def _get_actors_for_event(self, filters: dict[str, Any], event_name: str, properties=None, success=True):
        serialized_actors = get_actors(
            filters,
            self.team,
            funnelCorrelationPersonConverted=success,
            funnelCorrelationPersonEntity=EventsNode(event=event_name, properties=properties),
        )
        return [str(row[0]) for row in serialized_actors]

    def _get_actors_for_property(
        self, filters: dict[str, Any], property_values: list, success=True, funnelCorrelationNames=None
    ):
        funnelCorrelationPropertyValues = [
            (
                PersonPropertyFilter(key=prop, value=value, operator=PropertyOperator.EXACT)
                if type == "person"
                else GroupPropertyFilter(
                    key=prop, value=value, group_type_index=group_type_index, operator=PropertyOperator.EXACT
                )
            )
            for prop, value, type, group_type_index in property_values
        ]

        serialized_actors = get_actors(
            filters,
            self.team,
            funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES,
            funnelCorrelationNames=funnelCorrelationNames,
            funnelCorrelationPersonConverted=success,
            funnelCorrelationPropertyValues=funnelCorrelationPropertyValues,
        )
        return [str(row[0]) for row in serialized_actors]

    def test_basic_funnel_correlation_with_events(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        result, _ = self._get_events_for_filters(filters, funnelCorrelationType=FunnelCorrelationResultsType.EVENTS)

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [11, 1 / 11]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related",
                    "success_count": 5,
                    "failure_count": 0,
                    # "odds_ratio": 11.0,
                    "correlation_type": "success",
                },
                {
                    "event": "negatively_related",
                    "success_count": 0,
                    "failure_count": 5,
                    # "odds_ratio": 1 / 11,
                    "correlation_type": "failure",
                },
            ],
        )

        self.assertEqual(len(self._get_actors_for_event(filters, "positively_related")), 5)
        self.assertEqual(
            len(self._get_actors_for_event(filters, "positively_related", success=False)),
            0,
        )
        self.assertEqual(
            len(self._get_actors_for_event(filters, "negatively_related", success=False)),
            5,
        )
        self.assertEqual(len(self._get_actors_for_event(filters, "negatively_related")), 0)

        # Now exclude positively_related
        result, _ = self._get_events_for_filters(
            filters,
            funnelCorrelationType=FunnelCorrelationResultsType.EVENTS,
            funnelCorrelationExcludeEventNames=["positively_related"],
        )

        odds_ratio = result[0].pop("odds_ratio")
        expected_odds_ratio = 1 / 11

        self.assertAlmostEqual(odds_ratio, expected_odds_ratio)

        self.assertEqual(
            result,
            [
                {
                    "event": "negatively_related",
                    "success_count": 0,
                    "failure_count": 5,
                    # "odds_ratio": 1 / 11,
                    "correlation_type": "failure",
                }
            ],
        )
        # Getting specific people isn't affected by exclude_events
        self.assertEqual(len(self._get_actors_for_event(filters, "positively_related")), 5)
        self.assertEqual(
            len(self._get_actors_for_event(filters, "positively_related", success=False)),
            0,
        )
        self.assertEqual(
            len(self._get_actors_for_event(filters, "negatively_related", success=False)),
            5,
        )
        self.assertEqual(len(self._get_actors_for_event(filters, "negatively_related")), 0)

    @snapshot_clickhouse_queries
    def test_action_events_are_excluded_from_correlations(self):
        journey = {}

        for i in range(3):
            person_id = f"user_{i}"
            events = [
                {
                    "event": "user signed up",
                    "timestamp": "2020-01-02T14:00:00",
                    "properties": {"key": "val"},
                },
                # same event, but missing property, so not part of action.
                {"event": "user signed up", "timestamp": "2020-01-02T14:10:00"},
            ]
            if i % 2 == 0:
                events.append({"event": "positively_related", "timestamp": "2020-01-03T14:00:00"})
            events.append(
                {
                    "event": "paid",
                    "timestamp": "2020-01-04T14:00:00",
                    "properties": {"key": "val"},
                }
            )

            journey[person_id] = events

        # one failure needed
        journey["failure"] = [
            {
                "event": "user signed up",
                "timestamp": "2020-01-02T14:00:00",
                "properties": {"key": "val"},
            }
        ]

        journeys_for(events_by_person=journey, team=self.team)  # type: ignore

        sign_up_action = _create_action(
            name="user signed up",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )

        paid_action = _create_action(
            name="paid",
            team=self.team,
            properties=[{"key": "key", "type": "event", "value": ["val"], "operator": "exact"}],
        )
        filters = {
            "events": [],
            "actions": [
                {"id": sign_up_action.id, "order": 0},
                {"id": paid_action.id, "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
        }

        result, _ = self._get_events_for_filters(filters)

        #  missing user signed up and paid from result set, as expected
        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related",
                    "success_count": 2,
                    "failure_count": 0,
                    "odds_ratio": 3,
                    "correlation_type": "success",
                }
            ],
        )

    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_funnel_correlation_with_events_and_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:7",
            properties={"industry": "finance"},
        )

        for i in range(10, 20):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={},
            )
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
                properties={"$group_0": f"org:{i}"},
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                    properties={"$group_0": f"org:{i}"},
                )
                # this event shouldn't show up when dealing with groups
                _create_event(
                    team=self.team,
                    event="positively_related_without_group",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
                properties={"$group_0": f"org:{i}"},
            )

        # one fail group
        _create_person(distinct_ids=[f"user_fail"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_fail",
            timestamp="2020-01-02T14:00:00Z",
            properties={"$group_0": f"org:5"},
        )
        _create_event(
            team=self.team,
            event="negatively_related",
            distinct_id=f"user_{i}",
            timestamp="2020-01-03T14:00:00Z",
            properties={"$group_0": f"org:5"},
        )

        # one success group with same filter property
        _create_person(distinct_ids=[f"user_succ"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_succ",
            timestamp="2020-01-02T14:00:00Z",
            properties={"$group_0": f"org:7"},
        )
        _create_event(
            team=self.team,
            event="negatively_related",
            distinct_id=f"user_{i}",
            timestamp="2020-01-03T14:00:00Z",
            properties={"$group_0": f"org:7"},
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id=f"user_succ",
            timestamp="2020-01-04T14:00:00Z",
            properties={"$group_0": f"org:7"},
        )

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "aggregation_group_type_index": 0,
        }

        result, _ = self._get_events_for_filters(filters, funnelCorrelationType=FunnelCorrelationResultsType.EVENTS)

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [12 / 7, 1 / 11]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related",
                    "success_count": 5,
                    "failure_count": 0,
                    # "odds_ratio": 12/7,
                    "correlation_type": "success",
                },
                {
                    "event": "negatively_related",
                    "success_count": 1,
                    "failure_count": 1,
                    # "odds_ratio": 1 / 11,
                    "correlation_type": "failure",
                },
            ],
        )

        self.assertEqual(len(self._get_actors_for_event(filters, "positively_related")), 5)
        self.assertEqual(
            len(self._get_actors_for_event(filters, "positively_related", success=False)),
            0,
        )
        self.assertEqual(len(self._get_actors_for_event(filters, "negatively_related")), 1)
        self.assertEqual(
            len(self._get_actors_for_event(filters, "negatively_related", success=False)),
            1,
        )

        # Now exclude all groups in positive
        excludes = {
            "properties": [
                {
                    "key": "industry",
                    "value": "finance",
                    "type": "group",
                    "group_type_index": 0,
                }
            ]
        }

        result, _ = self._get_events_for_filters({**filters, **excludes})  # TODO destructure

        odds_ratio = result[0].pop("odds_ratio")
        expected_odds_ratio = 1
        # success total and failure totals remove other groups too

        self.assertAlmostEqual(odds_ratio, expected_odds_ratio)

        self.assertEqual(
            result,
            [
                {
                    "event": "negatively_related",
                    "success_count": 1,
                    "failure_count": 1,
                    # "odds_ratio": 1,
                    "correlation_type": "failure",
                }
            ],
        )

        self.assertEqual(len(self._get_actors_for_event(filters, "negatively_related")), 1)
        self.assertEqual(
            len(self._get_actors_for_event(filters, "negatively_related", success=False)),
            1,
        )

    @also_test_with_materialized_columns(
        event_properties=[], person_properties=["$browser"], verify_no_jsonextract=False
    )
    @freeze_time("2019-12-31")
    @snapshot_clickhouse_queries
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
            "funnel_correlation_names": ["$browser"],
        }

        for i in range(10):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Positive"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Negative"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        # One Positive with failure
        _create_person(
            distinct_ids=[f"user_fail"],
            team_id=self.team.pk,
            properties={"$browser": "Positive"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_fail",
            timestamp="2020-01-02T14:00:00Z",
        )

        # One Negative with success
        _create_person(
            distinct_ids=[f"user_succ"],
            team_id=self.team.pk,
            properties={"$browser": "Negative"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_succ",
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id=f"user_succ",
            timestamp="2020-01-04T14:00:00Z",
        )

        result, _ = self._get_events_for_filters(
            filters, funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES, funnelCorrelationNames=["$browser"]
        )

        odds_ratios = [item.pop("odds_ratio") for item in result]

        # Success Total = 11, Failure Total = 11
        #
        # Browser::Positive
        # Success: 10
        # Failure: 1

        # Browser::Negative
        # Success: 1
        # Failure: 10

        prior_count = 1
        expected_odds_ratios = [
            ((10 + prior_count) / (1 + prior_count)) * ((11 - 1 + prior_count) / (11 - 10 + prior_count)),
            ((1 + prior_count) / (10 + prior_count)) * ((11 - 10 + prior_count) / (11 - 1 + prior_count)),
        ]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "$browser::Positive",
                    "success_count": 10,
                    "failure_count": 1,
                    # "odds_ratio": 121/4,
                    "correlation_type": "success",
                },
                {
                    "event": "$browser::Negative",
                    "success_count": 1,
                    "failure_count": 10,
                    # "odds_ratio": 4/121,
                    "correlation_type": "failure",
                },
            ],
        )

        self.assertEqual(
            len(
                self._get_actors_for_property(
                    filters, [("$browser", "Positive", "person", None)], funnelCorrelationNames=["$browser"]
                )
            ),
            10,
        )
        self.assertEqual(
            len(
                self._get_actors_for_property(
                    filters, [("$browser", "Positive", "person", None)], False, funnelCorrelationNames=["$browser"]
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                self._get_actors_for_property(
                    filters, [("$browser", "Negative", "person", None)], funnelCorrelationNames=["$browser"]
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                self._get_actors_for_property(
                    filters, [("$browser", "Negative", "person", None)], False, funnelCorrelationNames=["$browser"]
                )
            ),
            10,
        )

    # TODO: Delete this test when moved to person-on-events
    @also_test_with_materialized_columns(
        event_properties=[], person_properties=["$browser"], verify_no_jsonextract=False
    )
    @snapshot_clickhouse_queries
    def test_funnel_correlation_with_properties_and_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": "positive"},
            )
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Positive"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
                properties={"$group_0": f"org:{i}"},
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
                properties={"$group_0": f"org:{i}"},
            )

        for i in range(10, 20):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": "negative"},
            )
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Negative"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
                properties={"$group_0": f"org:{i}"},
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                    properties={"$group_0": f"org:{i}"},
                )

        # One Positive with failure
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:fail",
            properties={"industry": "positive"},
        )
        _create_person(
            distinct_ids=[f"user_fail"],
            team_id=self.team.pk,
            properties={"$browser": "Positive"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_fail",
            timestamp="2020-01-02T14:00:00Z",
            properties={"$group_0": f"org:fail"},
        )

        # One Negative with success
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:succ",
            properties={"industry": "negative"},
        )
        _create_person(
            distinct_ids=[f"user_succ"],
            team_id=self.team.pk,
            properties={"$browser": "Negative"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_succ",
            timestamp="2020-01-02T14:00:00Z",
            properties={"$group_0": f"org:succ"},
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id=f"user_succ",
            timestamp="2020-01-04T14:00:00Z",
            properties={"$group_0": f"org:succ"},
        )

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "aggregation_group_type_index": 0,
        }

        result, _ = self._get_events_for_filters(
            filters, funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES, funnelCorrelationNames=["industry"]
        )

        odds_ratios = [item.pop("odds_ratio") for item in result]

        # Success Total = 11, Failure Total = 11
        #
        # Industry::Positive
        # Success: 10
        # Failure: 1

        # Industry::Negative
        # Success: 1
        # Failure: 10

        prior_count = 1
        expected_odds_ratios = [
            ((10 + prior_count) / (1 + prior_count)) * ((11 - 1 + prior_count) / (11 - 10 + prior_count)),
            ((1 + prior_count) / (10 + prior_count)) * ((11 - 10 + prior_count) / (11 - 1 + prior_count)),
        ]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "industry::positive",
                    "success_count": 10,
                    "failure_count": 1,
                    # "odds_ratio": 121/4,
                    "correlation_type": "success",
                },
                {
                    "event": "industry::negative",
                    "success_count": 1,
                    "failure_count": 10,
                    # "odds_ratio": 4/121,
                    "correlation_type": "failure",
                },
            ],
        )

        self.assertEqual(
            len(
                self._get_actors_for_property(
                    filters, [("industry", "positive", "group", 0)], funnelCorrelationNames=["industry"]
                )
            ),
            10,
        )
        self.assertEqual(
            len(self._get_actors_for_property(filters, [("industry", "positive", "group", 0)], False)),
            1,
        )
        self.assertEqual(
            len(self._get_actors_for_property(filters, [("industry", "negative", "group", 0)])),
            1,
        )
        self.assertEqual(
            len(self._get_actors_for_property(filters, [("industry", "negative", "group", 0)], False)),
            10,
        )

        # test with `$all` as property
        # _run property correlation with filter on all properties
        new_result, _ = self._get_events_for_filters(
            filters, funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES, funnelCorrelationNames=["$all"]
        )

        odds_ratios = [item.pop("odds_ratio") for item in new_result]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(new_result, result)

    @also_test_with_materialized_columns(
        event_properties=[],
        person_properties=["$browser"],
        verify_no_jsonextract=False,
    )
    @also_test_with_person_on_events_v2
    @snapshot_clickhouse_queries
    def test_funnel_correlation_with_properties_and_groups_person_on_events(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": "positive"},
            )
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Positive"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
                properties={"$group_0": f"org:{i}"},
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
                properties={"$group_0": f"org:{i}"},
            )

        for i in range(10, 20):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": "negative"},
            )
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Negative"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
                properties={"$group_0": f"org:{i}"},
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                    properties={"$group_0": f"org:{i}"},
                )

        # One Positive with failure
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:fail",
            properties={"industry": "positive"},
        )
        _create_person(
            distinct_ids=[f"user_fail"],
            team_id=self.team.pk,
            properties={"$browser": "Positive"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_fail",
            timestamp="2020-01-02T14:00:00Z",
            properties={"$group_0": f"org:fail"},
        )

        # One Negative with success
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=f"org:succ",
            properties={"industry": "negative"},
        )
        _create_person(
            distinct_ids=[f"user_succ"],
            team_id=self.team.pk,
            properties={"$browser": "Negative"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_succ",
            timestamp="2020-01-02T14:00:00Z",
            properties={"$group_0": f"org:succ"},
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id=f"user_succ",
            timestamp="2020-01-04T14:00:00Z",
            properties={"$group_0": f"org:succ"},
        )

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "aggregation_group_type_index": 0,
        }

        with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
            result, _ = self._get_events_for_filters(
                filters,
                funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES,
                funnelCorrelationNames=["industry"],
            )

            odds_ratios = [item.pop("odds_ratio") for item in result]

            # Success Total = 11, Failure Total = 11
            #
            # Industry::Positive
            # Success: 10
            # Failure: 1

            # Industry::Negative
            # Success: 1
            # Failure: 10

            prior_count = 1
            expected_odds_ratios = [
                ((10 + prior_count) / (1 + prior_count)) * ((11 - 1 + prior_count) / (11 - 10 + prior_count)),
                ((1 + prior_count) / (10 + prior_count)) * ((11 - 10 + prior_count) / (11 - 1 + prior_count)),
            ]

            for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
                self.assertAlmostEqual(odds, expected_odds)

            self.assertEqual(
                result,
                [
                    {
                        "event": "industry::positive",
                        "success_count": 10,
                        "failure_count": 1,
                        # "odds_ratio": 121/4,
                        "correlation_type": "success",
                    },
                    {
                        "event": "industry::negative",
                        "success_count": 1,
                        "failure_count": 10,
                        # "odds_ratio": 4/121,
                        "correlation_type": "failure",
                    },
                ],
            )

            self.assertEqual(
                len(self._get_actors_for_property(filters, [("industry", "positive", "group", 0)])),
                10,
            )
            self.assertEqual(
                len(self._get_actors_for_property(filters, [("industry", "positive", "group", 0)], False)),
                1,
            )
            self.assertEqual(
                len(self._get_actors_for_property(filters, [("industry", "negative", "group", 0)])),
                1,
            )
            self.assertEqual(
                len(self._get_actors_for_property(filters, [("industry", "negative", "group", 0)], False)),
                10,
            )

            # test with `$all` as property
            # _run property correlation with filter on all properties
            new_result, _ = self._get_events_for_filters(
                filters,
                funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES,
                funnelCorrelationNames=["$all"],
            )

            odds_ratios = [item.pop("odds_ratio") for item in new_result]

            for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
                self.assertAlmostEqual(odds, expected_odds)

            self.assertEqual(new_result, result)

    def test_no_divide_by_zero_errors(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        for i in range(2):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Positive"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            # failure count for this event is 0
            _create_event(
                team=self.team,
                event="positive",
                distinct_id=f"user_{i}",
                timestamp="2020-01-03T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(2, 4):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Negative"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                # success count for this event is 0
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        result, skewed_totals = self._get_events_for_filters(filters)

        self.assertFalse(skewed_totals)

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [9, 1 / 3]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positive",
                    "success_count": 2,
                    "failure_count": 0,
                    # "odds_ratio": 9.0,
                    "correlation_type": "success",
                },
                {
                    "event": "negatively_related",
                    "success_count": 0,
                    "failure_count": 1,
                    # "odds_ratio": 1 / 3,
                    "correlation_type": "failure",
                },
            ],
        )

    def test_correlation_with_properties_raises_validation_error(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        _create_person(
            distinct_ids=[f"user_1"],
            team_id=self.team.pk,
            properties={"$browser": "Positive"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_1",
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="rick",
            distinct_id=f"user_1",
            timestamp="2020-01-03T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id=f"user_1",
            timestamp="2020-01-04T14:00:00Z",
        )
        flush_persons_and_events()

        with self.assertRaises(ValidationError):
            self._get_events_for_filters(
                filters,
                funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES,
                # funnelCorrelationNames=["$browser"] -- missing
            )

        with self.assertRaises(ValidationError):
            self._get_events_for_filters(
                filters,
                funnelCorrelationType=FunnelCorrelationResultsType.EVENT_WITH_PROPERTIES,
                # "funnelCorrelationEventNames": ["rick"] -- missing
            )

    @also_test_with_materialized_columns(
        event_properties=[], person_properties=["$browser"], verify_no_jsonextract=False
    )
    @skip("Works locally and works after you tmate onto github actions and run it, but fails in CI")
    def test_correlation_with_multiple_properties(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        # 5 successful people with both properties
        for i in range(5):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Positive", "$nice": "very"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        # 10 successful people with some different properties
        for i in range(5, 15):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Positive", "$nice": "not"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        # 5 Unsuccessful people with some common properties
        for i in range(15, 20):
            _create_person(
                distinct_ids=[f"user_{i}"],
                team_id=self.team.pk,
                properties={"$browser": "Negative", "$nice": "smh"},
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )

        # One Positive with failure, no $nice property
        _create_person(
            distinct_ids=[f"user_fail"],
            team_id=self.team.pk,
            properties={"$browser": "Positive"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_fail",
            timestamp="2020-01-02T14:00:00Z",
        )

        # One Negative with success, no $nice property
        _create_person(
            distinct_ids=[f"user_succ"],
            team_id=self.team.pk,
            properties={"$browser": "Negative"},
        )
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_succ",
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id=f"user_succ",
            timestamp="2020-01-04T14:00:00Z",
        )

        result, _ = self._get_events_for_filters(
            filters,
            funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES,
            funnelCorrelationNames=["$browser", "$nice"],
        )

        # Success Total = 5 + 10 + 1 = 16
        # Failure Total = 5 + 1 = 6
        # Add 1 for priors

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [
            (16 / 2) * ((7 - 1) / (17 - 15)),
            (11 / 1) * ((7 - 0) / (17 - 10)),
            (6 / 1) * ((7 - 0) / (17 - 5)),
            (1 / 6) * ((7 - 5) / (17 - 0)),
            (2 / 6) * ((7 - 5) / (17 - 1)),
            (2 / 2) * ((7 - 1) / (17 - 1)),
        ]
        # (success + 1) / (failure + 1)

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        expected_result = [
            {
                "event": "$browser::Positive",
                "success_count": 15,
                "failure_count": 1,
                # "odds_ratio": 24,
                "correlation_type": "success",
            },
            {
                "event": "$nice::not",
                "success_count": 10,
                "failure_count": 0,
                # "odds_ratio": 11,
                "correlation_type": "success",
            },
            {
                "event": "$nice::very",
                "success_count": 5,
                "failure_count": 0,
                # "odds_ratio": 3.5,
                "correlation_type": "success",
            },
            {
                "event": "$nice::smh",
                "success_count": 0,
                "failure_count": 5,
                # "odds_ratio": 0.0196078431372549,
                "correlation_type": "failure",
            },
            {
                "event": "$browser::Negative",
                "success_count": 1,
                "failure_count": 5,
                # "odds_ratio": 0.041666666666666664,
                "correlation_type": "failure",
            },
            {
                "event": "$nice::",
                "success_count": 1,
                "failure_count": 1,
                # "odds_ratio": 0.375,
                "correlation_type": "failure",
            },
        ]

        self.assertEqual(result, expected_result)

        # _run property correlation with filter on all properties
        new_result, _ = self._get_events_for_filters(
            filters, funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES, funnelCorrelationNames=["$all"]
        )

        odds_ratios = [item.pop("odds_ratio") for item in new_result]

        new_expected_odds_ratios = expected_odds_ratios[:-1]
        new_expected_result = expected_result[:-1]
        # When querying all properties, we don't consider properties that don't exist for part of the data
        # since users aren't explicitly asking for that property. Thus,
        # We discard $nice:: because it's an empty result set

        for odds, expected_odds in zip(odds_ratios, new_expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(new_result, new_expected_result)

        # search for $all but exclude $browser
        new_result, _ = self._get_events_for_filters(
            filters,
            funnelCorrelationType=FunnelCorrelationResultsType.PROPERTIES,
            funnelCorrelationNames=["$all"],
            funnelCorrelationExcludeNames=["$browser"],
        )

        odds_ratios = [item.pop("odds_ratio") for item in new_result]

        new_expected_odds_ratios = expected_odds_ratios[1:4]  # choosing the $nice property values
        new_expected_result = expected_result[1:4]

        for odds, expected_odds in zip(odds_ratios, new_expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(new_result, new_expected_result)

        self.assertEqual(
            len(
                self._get_actors_for_property(
                    filters, [("$nice", "not", "person", None)], funnelCorrelationNames=["$browser", "$nice"]
                )
            ),
            10,
        )
        # self.assertEqual(
        #     len(
        #         self._get_actors_for_property(
        #             filters, [("$nice", "", "person", None)], False, funnelCorrelationNames=["$browser", "$nice"]
        #         )
        #     ),
        #     1,
        # )
        self.assertEqual(
            len(
                self._get_actors_for_property(
                    filters, [("$nice", "very", "person", None)], funnelCorrelationNames=["$browser", "$nice"]
                )
            ),
            5,
        )

    def test_discarding_insignificant_events(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
            if i % 10 == 0:
                _create_event(
                    team=self.team,
                    event="low_sig_positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:20:00Z",
                )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
            if i % 5 == 0:
                _create_event(
                    team=self.team,
                    event="low_sig_negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        #  Total 10 positive, 10 negative
        # low sig count = 1 and 2, high sig count >= 5
        # Thus, to discard the low sig count, % needs to be >= 10%, or count >= 2

        # Discard both due to %
        FunnelCorrelationQueryRunner.MIN_PERSON_PERCENTAGE = 0.11
        FunnelCorrelationQueryRunner.MIN_PERSON_COUNT = 25
        result, _ = self._get_events_for_filters(filters, funnelCorrelationType=FunnelCorrelationResultsType.EVENTS)

        self.assertEqual(len(result), 2)

    def test_events_within_conversion_window_for_correlation(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_interval": "10",
            "funnel_window_interval_unit": "minute",
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        _create_person(distinct_ids=["user_successful"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="user_successful",
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="positively_related",
            distinct_id="user_successful",
            timestamp="2020-01-02T14:02:00Z",
        )
        _create_event(
            team=self.team,
            event="paid",
            distinct_id="user_successful",
            timestamp="2020-01-02T14:06:00Z",
        )

        _create_person(distinct_ids=["user_dropoff"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id="user_dropoff",
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="NOT_negatively_related",
            distinct_id="user_dropoff",
            timestamp="2020-01-02T14:15:00Z",  # event happened outside conversion window
        )

        result, _ = self._get_events_for_filters(filters, funnelCorrelationType=FunnelCorrelationResultsType.EVENTS)

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [4]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related",
                    "success_count": 1,
                    "failure_count": 0,
                    # "odds_ratio": 4.0,
                    "correlation_type": "success",
                }
            ],
        )

    @also_test_with_materialized_columns(["blah", "signup_source"], verify_no_jsonextract=False)
    def test_funnel_correlation_with_event_properties(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                    properties={
                        "signup_source": "facebook" if i % 4 == 0 else "email",
                        "blah": "value_bleh",
                    },
                )
                # source: email occurs only twice, so would be discarded from result set
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                    properties={"signup_source": "shazam" if i % 6 == 0 else "email"},
                )
                # source: shazam occurs only once, so would be discarded from result set

        result, _ = self._get_events_for_filters(
            filters,
            funnelCorrelationType=FunnelCorrelationResultsType.EVENT_WITH_PROPERTIES,
            funnelCorrelationEventNames=[
                "positively_related",
                "negatively_related",
            ],
        )

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [11, 5.5, 2 / 11]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related::blah::value_bleh",
                    "success_count": 5,
                    "failure_count": 0,
                    # "odds_ratio": 11.0,
                    "correlation_type": "success",
                },
                {
                    "event": "positively_related::signup_source::facebook",
                    "success_count": 3,
                    "failure_count": 0,
                    # "odds_ratio": 5.5,
                    "correlation_type": "success",
                },
                {
                    "event": "negatively_related::signup_source::email",
                    "success_count": 0,
                    "failure_count": 3,
                    # "odds_ratio": 0.18181818181818182,
                    "correlation_type": "failure",
                },
            ],
        )

        self.assertEqual(
            len(
                self._get_actors_for_event(
                    filters,
                    "positively_related",
                    [EventPropertyFilter(operator=PropertyOperator.EXACT, key="blah", value="value_bleh")],
                )
            ),
            5,
        )
        self.assertEqual(
            len(
                self._get_actors_for_event(
                    filters,
                    "positively_related",
                    [EventPropertyFilter(operator=PropertyOperator.EXACT, key="signup_source", value="facebook")],
                )
            ),
            3,
        )
        self.assertEqual(
            len(
                self._get_actors_for_event(
                    filters,
                    "positively_related",
                    [EventPropertyFilter(operator=PropertyOperator.EXACT, key="signup_source", value="facebook")],
                    False,
                )
            ),
            0,
        )
        self.assertEqual(
            len(
                self._get_actors_for_event(
                    filters,
                    "negatively_related",
                    [EventPropertyFilter(operator=PropertyOperator.EXACT, key="signup_source", value="email")],
                    False,
                )
            ),
            3,
        )

    @also_test_with_materialized_columns(["blah", "signup_source"], verify_no_jsonextract=False)
    @snapshot_clickhouse_queries
    def test_funnel_correlation_with_event_properties_and_groups(self):
        # same test as test_funnel_correlation_with_event_properties but with events attached to groups
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=1
        )

        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key=f"org:{i}",
                properties={"industry": "positive"},
            )
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
                properties={"$group_1": f"org:{i}"},
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                    properties={
                        "signup_source": "facebook" if i % 4 == 0 else "email",
                        "blah": "value_bleh",
                        "$group_1": f"org:{i}",
                    },
                )
                # source: email occurs only twice, so would be discarded from result set
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
                properties={"$group_1": f"org:{i}"},
            )

        for i in range(10, 20):
            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key=f"org:{i}",
                properties={"industry": "positive"},
            )
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
                properties={"$group_1": f"org:{i}"},
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                    properties={
                        "signup_source": "shazam" if i % 6 == 0 else "email",
                        "$group_1": f"org:{i}",
                    },
                )
                # source: shazam occurs only once, so would be discarded from result set

        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "aggregation_group_type_index": 1,
        }

        result, _ = self._get_events_for_filters(
            filters,
            funnelCorrelationType=FunnelCorrelationResultsType.EVENT_WITH_PROPERTIES,
            funnelCorrelationEventNames=[
                "positively_related",
                "negatively_related",
            ],
        )

        odds_ratios = [item.pop("odds_ratio") for item in result]
        expected_odds_ratios = [11, 5.5, 2 / 11]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related::blah::value_bleh",
                    "success_count": 5,
                    "failure_count": 0,
                    # "odds_ratio": 11.0,
                    "correlation_type": "success",
                },
                {
                    "event": "positively_related::signup_source::facebook",
                    "success_count": 3,
                    "failure_count": 0,
                    # "odds_ratio": 5.5,
                    "correlation_type": "success",
                },
                {
                    "event": "negatively_related::signup_source::email",
                    "success_count": 0,
                    "failure_count": 3,
                    # "odds_ratio": 0.18181818181818182,
                    "correlation_type": "failure",
                },
            ],
        )

    def test_funnel_correlation_with_event_properties_exclusions(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        # Need more than 2 events to get a correlation
        for i in range(3):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="positively_related",
                distinct_id=f"user_{i}",
                timestamp="2020-01-03T14:00:00Z",
                properties={"signup_source": "facebook", "blah": "value_bleh"},
            )
            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        # Atleast one person that fails, to ensure we get results
        _create_person(distinct_ids=[f"user_fail"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_fail",
            timestamp="2020-01-02T14:00:00Z",
        )

        result, _ = self._get_events_for_filters(
            filters,
            funnelCorrelationType=FunnelCorrelationResultsType.EVENT_WITH_PROPERTIES,
            funnelCorrelationEventNames=["positively_related"],
            funnelCorrelationEventExcludePropertyNames=["signup_source"],
        )

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related::blah::value_bleh",
                    "success_count": 3,
                    "failure_count": 0,
                    "odds_ratio": 8,
                    "correlation_type": "success",
                },
                #  missing signup_source, as expected
            ],
        )

        self.assertEqual(
            len(
                self._get_actors_for_event(
                    filters,
                    "positively_related",
                    [EventPropertyFilter(operator=PropertyOperator.EXACT, key="blah", value="value_bleh")],
                )
            ),
            3,
        )

        # If you search for persons with a specific property, even if excluded earlier, you should get them
        self.assertEqual(
            len(
                self._get_actors_for_event(
                    filters,
                    "positively_related",
                    [EventPropertyFilter(operator=PropertyOperator.EXACT, key="signup_source", value="facebook")],
                )
            ),
            3,
        )

    # :FIXME: This should also work with materialized columns
    # @also_test_with_materialized_columns(["$event_type", "signup_source"])
    def test_funnel_correlation_with_event_properties_autocapture(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        # Need a minimum of 3 hits to get a correlation result
        for i in range(6):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id=f"user_{i}",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id=f"user_{i}",
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="a", href="/movie")],
                timestamp="2020-01-03T14:00:00Z",
                properties={"signup_source": "email", "$event_type": "click"},
            )
            # Test two different types of autocapture elements, with different counts, so we can accurately test results
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="$autocapture",
                    distinct_id=f"user_{i}",
                    elements=[
                        Element(
                            nth_of_type=1,
                            nth_child=0,
                            tag_name="button",
                            text="Pay $10",
                        )
                    ],
                    timestamp="2020-01-03T14:00:00Z",
                    properties={"signup_source": "facebook", "$event_type": "submit"},
                )

            _create_event(
                team=self.team,
                event="paid",
                distinct_id=f"user_{i}",
                timestamp="2020-01-04T14:00:00Z",
            )

        # Atleast one person that fails, to ensure we get results
        _create_person(distinct_ids=[f"user_fail"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="user signed up",
            distinct_id=f"user_fail",
            timestamp="2020-01-02T14:00:00Z",
        )

        result, _ = self._get_events_for_filters(
            filters,
            funnelCorrelationType=FunnelCorrelationResultsType.EVENT_WITH_PROPERTIES,
            funnelCorrelationEventNames=["$autocapture"],
        )

        # $autocapture results only return elements chain
        self.assertEqual(
            result,
            [
                {
                    "event": '$autocapture::elements_chain::click__~~__a:href="/movie"nth-child="0"nth-of-type="1"',
                    "success_count": 6,
                    "failure_count": 0,
                    "odds_ratio": 14.0,
                    "correlation_type": "success",
                },
                {
                    "event": '$autocapture::elements_chain::submit__~~__button:nth-child="0"nth-of-type="1"text="Pay $10"',
                    "success_count": 3,
                    "failure_count": 0,
                    "odds_ratio": 2.0,
                    "correlation_type": "success",
                },
            ],
        )

        # self.assertEqual(
        #     len(self._get_actors_for_event(filter, "$autocapture", {"signup_source": "facebook"})),
        #     3,
        # )
        # self.assertEqual(
        #     len(self._get_actors_for_event(filter, "$autocapture", {"$event_type": "click"})),
        #     6,
        # )
        # self.assertEqual(
        #     len(
        #         self._get_actors_for_event(
        #             filter,
        #             "$autocapture",
        #             [
        #                 {
        #                     "key": "tag_name",
        #                     "operator": "exact",
        #                     "type": "element",
        #                     "value": "button",
        #                 },
        #                 {
        #                     "key": "text",
        #                     "operator": "exact",
        #                     "type": "element",
        #                     "value": "Pay $10",
        #                 },
        #             ],
        #         )
        #     ),
        #     3,
        # )
        # self.assertEqual(
        #     len(
        #         self._get_actors_for_event(
        #             filter,
        #             "$autocapture",
        #             [
        #                 {
        #                     "key": "tag_name",
        #                     "operator": "exact",
        #                     "type": "element",
        #                     "value": "a",
        #                 },
        #                 {
        #                     "key": "href",
        #                     "operator": "exact",
        #                     "type": "element",
        #                     "value": "/movie",
        #                 },
        #             ],
        #         )
        #     ),
        #     6,
        # )


class TestClickhouseFunnelCorrelation(BaseTestClickhouseFunnelCorrelation):
    __test__ = True


class TestCorrelationFunctions(unittest.TestCase):
    def test_are_results_insignificant(self):
        # Same setup as above test: test_discarding_insignificant_events
        contingency_tables = [
            EventContingencyTable(
                event="negatively_related",
                visited=EventStats(success_count=0, failure_count=5),
                success_total=10,
                failure_total=10,
            ),
            EventContingencyTable(
                event="positively_related",
                visited=EventStats(success_count=5, failure_count=0),
                success_total=10,
                failure_total=10,
            ),
            EventContingencyTable(
                event="low_sig_negatively_related",
                visited=EventStats(success_count=0, failure_count=2),
                success_total=10,
                failure_total=10,
            ),
            EventContingencyTable(
                event="low_sig_positively_related",
                visited=EventStats(success_count=1, failure_count=0),
                success_total=10,
                failure_total=10,
            ),
        ]

        # Discard both low_sig due to %
        FunnelCorrelationQueryRunner.MIN_PERSON_PERCENTAGE = 0.11
        FunnelCorrelationQueryRunner.MIN_PERSON_COUNT = 25
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelationQueryRunner.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 2)

        # Discard one low_sig due to %
        FunnelCorrelationQueryRunner.MIN_PERSON_PERCENTAGE = 0.051
        FunnelCorrelationQueryRunner.MIN_PERSON_COUNT = 25
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelationQueryRunner.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 3)

        # Discard both due to count
        FunnelCorrelationQueryRunner.MIN_PERSON_PERCENTAGE = 0.5
        FunnelCorrelationQueryRunner.MIN_PERSON_COUNT = 3
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelationQueryRunner.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 2)

        # Discard one due to count
        FunnelCorrelationQueryRunner.MIN_PERSON_PERCENTAGE = 0.5
        FunnelCorrelationQueryRunner.MIN_PERSON_COUNT = 2
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelationQueryRunner.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 3)

        # Discard everything due to %
        FunnelCorrelationQueryRunner.MIN_PERSON_PERCENTAGE = 0.5
        FunnelCorrelationQueryRunner.MIN_PERSON_COUNT = 100
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelationQueryRunner.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 0)

        # Discard everything due to count
        FunnelCorrelationQueryRunner.MIN_PERSON_PERCENTAGE = 0.5
        FunnelCorrelationQueryRunner.MIN_PERSON_COUNT = 6
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelationQueryRunner.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 0)
