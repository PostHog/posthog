from unittest.mock import Mock, patch

from posthog.hogql_queries.insights.funnels.test.test_funnel_trends_actors import BaseTestFunnelTrendsActors


@patch(
    "posthoganalytics.feature_enabled",
    new=Mock(side_effect=lambda key, *args, **kwargs: key == "insight-funnels-use-udf-trends"),
)
class TestFunnelTrendsActorsUDF(BaseTestFunnelTrendsActors):
    __test__ = True
