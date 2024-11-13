from datetime import datetime
from typing import cast
from unittest.mock import patch, Mock

from freezegun import freeze_time

from posthog.constants import FunnelOrderType, INSIGHT_FUNNELS
from posthog.hogql_queries.insights.funnels import Funnel
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.funnels.test.breakdown_cases import (
    funnel_breakdown_test_factory,
    funnel_breakdown_group_test_factory,
)
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Action
from posthog.schema import FunnelsQuery, FunnelsQueryResponse
from posthog.test.base import (
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)
from posthog.test.test_journeys import journeys_for
from test_funnel import funnel_test_factory, PseudoFunnelActors
from posthog.hogql_queries.insights.funnels.test.conversion_time_cases import (
    funnel_conversion_time_test_factory,
)


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

    maxDiff = None


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestFunnelConversionTimeUDF(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.ORDERED, PseudoFunnelActors),  # type: ignore
):
    maxDiff = None
    pass
