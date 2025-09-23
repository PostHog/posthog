from datetime import datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import Mock, patch

from test_funnel import PseudoFunnelActors, funnel_test_factory

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FunnelsFilter,
    FunnelsQuery,
    FunnelsQueryResponse,
    PropertyOperator,
)

from posthog.constants import INSIGHT_FUNNELS, FunnelOrderType
from posthog.hogql_queries.insights.funnels import Funnel
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.breakdown_cases import (
    funnel_breakdown_group_test_factory,
    funnel_breakdown_test_factory,
)
from posthog.hogql_queries.insights.funnels.test.conversion_time_cases import funnel_conversion_time_test_factory
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Action
from posthog.test.test_journeys import journeys_for


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name, "properties": properties}])
    return action


use_udf_funnel_flag_side_effect = lambda key, *args, **kwargs: key == "insight-funnels-use-udf"


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestFunnelBreakdownUDF(
    ClickhouseTestMixin,
    funnel_breakdown_test_factory(  # type: ignore
        FunnelOrderType.ORDERED,
        PseudoFunnelActors,
        _create_action,
        _create_person,
    ),
):
    maxDiff = None
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestFunnelGroupBreakdownUDF(
    ClickhouseTestMixin,
    funnel_breakdown_group_test_factory(  # type: ignore
        FunnelOrderType.ORDERED,
        PseudoFunnelActors,
    ),
):
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestFOSSFunnelUDF(funnel_test_factory(Funnel, _create_event, _create_person)):  # type: ignore
    def test_assert_flag_is_on(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "steps",
            "interval": "hour",
            "date_from": "2021-05-01 00:00:00",
            "funnel_window_interval": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = cast(FunnelsQueryResponse, FunnelsQueryRunner(query=query, team=self.team).calculate())

        self.assertTrue(results.isUdf)

    def test_assert_trends_flag_is_off(self):
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "trends",
            "interval": "hour",
            "date_from": "2021-05-01 00:00:00",
            "funnel_window_interval": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = cast(FunnelsQueryResponse, FunnelsQueryRunner(query=query, team=self.team).calculate())

        self.assertFalse(results.isUdf)

    # Old style funnels fails on this (not sure why)
    def test_events_same_timestamp_no_exclusions(self):
        _create_person(distinct_ids=["test"], team_id=self.team.pk)
        with freeze_time("2024-01-10T12:01:00"):
            _create_event(team=self.team, event="step one, ten", distinct_id="test")
            _create_event(team=self.team, event="step two, three, seven", distinct_id="test")
            _create_event(team=self.team, event="step two, three, seven", distinct_id="test")
            _create_event(team=self.team, event="step four, five, eight", distinct_id="test")
            _create_event(team=self.team, event="step four, five, eight", distinct_id="test")
            _create_event(team=self.team, event="step six, nine", distinct_id="test")
            _create_event(team=self.team, event="step two, three, seven", distinct_id="test")
            _create_event(team=self.team, event="step four, five, eight", distinct_id="test")
            _create_event(team=self.team, event="step six, nine", distinct_id="test")
            _create_event(team=self.team, event="step one, ten", distinct_id="test")
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "steps",
            "date_from": "2024-01-10 00:00:00",
            "date_to": "2024-01-12 00:00:00",
            "events": [
                {"id": "step one, ten", "order": 0},
                {"id": "step two, three, seven", "order": 1},
                {"id": "step two, three, seven", "order": 2},
                {"id": "step four, five, eight", "order": 3},
                {"id": "step four, five, eight", "order": 4},
                {"id": "step six, nine", "order": 5},
                {"id": "step two, three, seven", "order": 6},
                {"id": "step four, five, eight", "order": 7},
                {"id": "step six, nine", "order": 8},
                {"id": "step one, ten", "order": 9},
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
        self.assertEqual(1, results[-1]["count"])

    # This is a change in behavior that only applies to UDFs - it seems more correct than what was happening before
    # In old style UDFs, an exclusion like this would still count, even if it were outside of the match window
    def test_excluded_after_time_expires(self):
        events = [
            {
                "event": "step one",
                "timestamp": datetime(2021, 5, 1, 0, 0, 0),
            },
            # Exclusion happens after time expires
            {
                "event": "exclusion",
                "timestamp": datetime(2021, 5, 1, 0, 0, 11),
            },
            {
                "event": "step two",
                "timestamp": datetime(2021, 5, 1, 0, 0, 12),
            },
        ]
        journeys_for(
            {
                "user_one": events,
            },
            self.team,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "steps",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-13 23:59:59",
            "funnel_window_interval": 10,
            "funnel_window_interval_unit": "second",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team, just_summarize=True).calculate().results

        self.assertEqual(1, results[0]["count"])
        self.assertEqual(0, results[1]["count"])

    def test_funnel_with_optional_steps(self):
        # Define all the different user journeys
        journeys_for(
            {
                "no_events": [],  # person who does nothing
                "step1_only": [{"event": "step one", "timestamp": datetime(2012, 1, 15, 0, 0, 0)}],
                "step123": [
                    {"event": "step one", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {"event": "step two", "timestamp": datetime(2012, 1, 15, 0, 1, 0)},
                    {"event": "step three", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                ],
                "step13": [
                    {"event": "step one", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {"event": "step three", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                ],
                "step12345": [
                    {"event": "step one", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {"event": "step two", "timestamp": datetime(2012, 1, 15, 0, 1, 0)},
                    {"event": "step three", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                    {"event": "step four", "timestamp": datetime(2012, 1, 15, 0, 3, 0)},
                    {"event": "step five", "timestamp": datetime(2012, 1, 15, 0, 4, 0)},
                ],
                "step1235": [
                    {"event": "step one", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {"event": "step two", "timestamp": datetime(2012, 1, 15, 0, 1, 0)},
                    {"event": "step three", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                    {"event": "step five", "timestamp": datetime(2012, 1, 15, 0, 4, 0)},
                ],
                "step134": [
                    {"event": "step one", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {"event": "step three", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                    {"event": "step four", "timestamp": datetime(2012, 1, 15, 0, 3, 0)},
                ],
                "step1345": [
                    {"event": "step one", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {"event": "step three", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                    {"event": "step four", "timestamp": datetime(2012, 1, 15, 0, 3, 0)},
                    {"event": "step five", "timestamp": datetime(2012, 1, 15, 0, 4, 0)},
                ],
                "step135": [
                    {"event": "step one", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {"event": "step three", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                    {"event": "step five", "timestamp": datetime(2012, 1, 15, 0, 4, 0)},
                ],
            },
            self.team,
        )

        query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step two", optionalInFunnel=True),  # Optional
                EventsNode(event="step three"),
                EventsNode(event="step four", optionalInFunnel=True),  # Optional
                EventsNode(event="step five"),
            ],
            dateRange=DateRange(
                date_from="2012-01-01 00:00:00",
                date_to="2012-02-01 23:59:59",
            ),
            funnelsFilter=FunnelsFilter(),
        )

        result = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(result[0]["name"], "step one")
        self.assertEqual(result[0]["count"], 8)  # all users who did at least step 1

        self.assertEqual(result[1]["name"], "step two")
        self.assertEqual(result[1]["count"], 3)  # users who did step 2 (optional)

        self.assertEqual(result[2]["name"], "step three")
        self.assertEqual(result[2]["count"], 7)  # users who did step 3 (required)

        self.assertEqual(result[3]["name"], "step four")
        self.assertEqual(result[3]["count"], 3)  # users who did step 4 (optional)

        self.assertEqual(result[4]["name"], "step five")
        self.assertEqual(result[4]["count"], 4)  # users who completed the funnel

    def test_funnel_with_optional_steps_same_event(self):
        # Define users with different numbers of the same event
        journeys_for(
            {
                "zero_events": [],  # person who does nothing
                "one_event": [{"event": "same_event", "timestamp": datetime(2012, 1, 15, 0, 0, 0)}],
                "two_events": [
                    {"event": "same_event", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {
                        "event": "same_event",
                        "timestamp": datetime(2012, 1, 15, 0, 1, 0),
                    },
                ],
                "three_events": [
                    {"event": "same_event", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {"event": "same_event", "timestamp": datetime(2012, 1, 15, 0, 1, 0)},
                    {"event": "same_event", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                ],
                "three_events_with_match": [
                    {"event": "same_event", "timestamp": datetime(2012, 1, 15, 0, 0, 0)},
                    {
                        "event": "same_event",
                        "timestamp": datetime(2012, 1, 15, 0, 1, 0),
                        "properties": {"$current_url": "url"},
                    },
                    {"event": "same_event", "timestamp": datetime(2012, 1, 15, 0, 2, 0)},
                ],
            },
            self.team,
        )

        query = FunnelsQuery(
            series=[
                EventsNode(event="same_event"),  # Step 1: required
                EventsNode(
                    event="same_event",
                    optionalInFunnel=True,
                ),  # Step 2: optional
                EventsNode(
                    event="same_event",
                    properties=[EventPropertyFilter(key="$current_url", operator=PropertyOperator.EXACT, value="url")],
                ),  # Step 3: required
                EventsNode(event="same_event"),  # Step 4: required
            ],
            dateRange=DateRange(
                date_from="2012-01-01 00:00:00",
                date_to="2012-02-01 23:59:59",
            ),
            funnelsFilter=FunnelsFilter(),
        )

        result = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(result[0]["name"], "same_event")
        self.assertEqual(result[0]["count"], 4)  # all users who did at least 1 event

        self.assertEqual(result[1]["name"], "same_event")
        self.assertEqual(result[1]["count"], 2)  # both of the users with two events and no $current_url

        self.assertEqual(result[2]["name"], "same_event")
        self.assertEqual(result[2]["count"], 1)  # the user with $current_url set in the second event

        self.assertEqual(result[3]["name"], "same_event")
        self.assertEqual(result[3]["count"], 1)  # the user with $current_url set in the second event

    maxDiff = None


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestFunnelConversionTimeUDF(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.ORDERED, PseudoFunnelActors),  # type: ignore
):
    maxDiff = None
    pass
