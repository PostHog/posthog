from posthog.hogql_queries.insights.funnels.test.test_funnel_unordered import (
    BaseTestFunnelUnorderedSteps,
    BaseTestFunnelUnorderedStepsBreakdown,
    BaseTestFunnelUnorderedStepsConversionTime,
)
from unittest.mock import Mock, patch


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelUnorderedStepsBreakdownUDF(BaseTestFunnelUnorderedStepsBreakdown):
    __test__ = True


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelUnorderedStepsConversionTimeUDF(BaseTestFunnelUnorderedStepsConversionTime):
    __test__ = True


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelUnorderedStepsUDF(BaseTestFunnelUnorderedSteps):
    __test__ = True
