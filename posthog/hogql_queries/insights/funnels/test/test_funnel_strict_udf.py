from unittest.mock import Mock, patch

from posthog.hogql_queries.insights.funnels.test.test_funnel_strict import BaseTestFunnelStrictStepsBreakdown


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelStrictStepsBreakdownUDF(BaseTestFunnelStrictStepsBreakdown):
    pass
