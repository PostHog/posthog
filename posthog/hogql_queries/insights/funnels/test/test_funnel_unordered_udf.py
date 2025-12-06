from posthog.hogql_queries.insights.funnels.test.test_funnel_unordered import (
    BaseTestFunnelUnorderedGroupBreakdown,
    BaseTestFunnelUnorderedSteps,
    BaseTestFunnelUnorderedStepsBreakdown,
    BaseTestFunnelUnorderedStepsConversionTime,
)


class TestFunnelUnorderedGroupBreakdownUDF(BaseTestFunnelUnorderedGroupBreakdown):
    __test__ = True


class TestFunnelUnorderedStepsBreakdownUDF(BaseTestFunnelUnorderedStepsBreakdown):
    __test__ = True


class TestFunnelUnorderedStepsConversionTimeUDF(BaseTestFunnelUnorderedStepsConversionTime):
    __test__ = True


class TestFunnelUnorderedStepsUDF(BaseTestFunnelUnorderedSteps):
    __test__ = True
