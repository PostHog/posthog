from typing import cast
from unittest.mock import patch, Mock

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


funnel_flag_side_effect = lambda key, *args, **kwargs: key == "insight-funnels-use-udf"


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=funnel_flag_side_effect))
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


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=funnel_flag_side_effect))
class TestFunnelGroupBreakdownUDF(
    ClickhouseTestMixin,
    funnel_breakdown_group_test_factory(  # type: ignore
        FunnelOrderType.ORDERED,
        ClickhouseFunnelActors,
    ),
):
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=funnel_flag_side_effect))
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

    maxDiff = None


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=funnel_flag_side_effect))
class TestFunnelConversionTimeUDF(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.ORDERED, ClickhouseFunnelActors),  # type: ignore
):
    maxDiff = None
    pass
