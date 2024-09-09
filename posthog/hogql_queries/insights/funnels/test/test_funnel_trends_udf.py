from unittest.mock import patch, Mock

from posthog.hogql_queries.insights.funnels.test.test_funnel_trends import BaseTestFunnelTrends


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelTrendsUDF(BaseTestFunnelTrends):
    pass
