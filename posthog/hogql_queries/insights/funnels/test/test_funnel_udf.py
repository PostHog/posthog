from unittest.mock import patch, Mock

from posthog.constants import FunnelOrderType
from posthog.hogql_queries.insights.funnels import Funnel
from posthog.hogql_queries.insights.funnels.test.breakdown_cases import (
    funnel_breakdown_test_factory,
    funnel_breakdown_group_test_factory,
)
from posthog.models import Action
from posthog.queries.funnels import ClickhouseFunnelActors
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


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
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


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelGroupBreakdownUDF(
    ClickhouseTestMixin,
    funnel_breakdown_group_test_factory(  # type: ignore
        FunnelOrderType.ORDERED,
        ClickhouseFunnelActors,
    ),
):
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFOSSFunnelUDF(funnel_test_factory(Funnel, _create_event, _create_person)):  # type: ignore
    maxDiff = None


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelConversionTimeUDF(
    ClickhouseTestMixin,
    funnel_conversion_time_test_factory(FunnelOrderType.ORDERED, ClickhouseFunnelActors),  # type: ignore
):
    maxDiff = None
    pass
