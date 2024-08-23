from unittest.mock import Mock, patch

from posthog.hogql_queries.insights.funnels.test.test_funnel_strict import (
    BaseTestFunnelStrictStepsBreakdown,
    BaseTestFunnelStrictSteps,
    BaseTestStrictFunnelGroupBreakdown,
    BaseTestFunnelStrictStepsConversionTime,
)


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelStrictStepsBreakdown(BaseTestFunnelStrictStepsBreakdown):
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelStrictSteps(BaseTestFunnelStrictSteps):
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestStrictFunnelGroupBreakdown(BaseTestStrictFunnelGroupBreakdown):
    pass


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestFunnelStrictStepsConversionTime(BaseTestFunnelStrictStepsConversionTime):
    pass
