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
from posthog.queries.funnels import ClickhouseFunnelActors
from posthog.schema import FunnelsQuery, FunnelsQueryResponse
from posthog.test.base import (
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)
from test_funnel import funnel_test_factory
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
        ClickhouseFunnelActors,
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
        ClickhouseFunnelActors,
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

    # This is to define the behavior of how UDFs handle exclusions for same timestamp events
    # It doesn't have to be this way, but better to have a clear definition than none at all
    def test_multiple_events_same_timestamp_exclusions(self):
        _create_person(distinct_ids=["test"], team_id=self.team.pk)
        with freeze_time("2024-01-10T12:00:00"):
            _create_event(team=self.team, event="step zero", distinct_id="test")
        with freeze_time("2024-01-10T12:01:00"):
            for _ in range(30):
                _create_event(team=self.team, event="step one", distinct_id="test")
            _create_event(team=self.team, event="exclusion", distinct_id="test")
            _create_event(team=self.team, event="step two", distinct_id="test")
        with freeze_time("2024-01-10T12:02:00"):
            _create_event(team=self.team, event="step three", distinct_id="test")
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "steps",
            "date_from": "2024-01-10 00:00:00",
            "date_to": "2024-01-12 00:00:00",
            "events": [
                {"id": "step zero", "order": 0},
                {"id": "step one", "order": 1},
                {"id": "step two", "order": 2},
                {"id": "step three", "order": 3},
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
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
        self.assertEqual(0, len(results))

        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": "steps",
            "date_from": "2024-01-10 00:00:00",
            "date_to": "2024-01-12 00:00:00",
            "events": [
                {"id": "step zero", "order": 0},
                {"id": "step one", "order": 1},
                {"id": "step two", "order": 2},
                {"id": "step three", "order": 3},
            ],
            "exclusions": [
                {
                    "id": "exclusion",
                    "type": "events",
                    "funnel_from_step": 1,
                    "funnel_to_step": 2,
                }
            ],
        }

        query = cast(FunnelsQuery, filter_to_query(filters))
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results
        self.assertEqual(1, results[-1]["count"])

    maxDiff = None


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestFunnelConversionTimeUDF(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.ORDERED, ClickhouseFunnelActors),  # type: ignore
):
    maxDiff = None
    pass
