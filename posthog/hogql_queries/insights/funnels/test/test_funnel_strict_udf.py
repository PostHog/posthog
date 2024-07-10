from unittest.mock import Mock, patch


from posthog.hogql_queries.insights.funnels.test.test_funnel_strict import TestFunnelStrictStepsBreakdown
from posthog.models.action import Action


FORMAT_TIME = "%Y-%m-%d 00:00:00"


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    properties = kwargs.pop("properties", {})
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name, "properties": properties}])
    return action


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelStrictStepsBreakdownUDF(TestFunnelStrictStepsBreakdown):
    pass
