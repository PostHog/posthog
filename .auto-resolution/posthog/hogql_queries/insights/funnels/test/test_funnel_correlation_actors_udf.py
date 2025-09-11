from unittest.mock import Mock, patch

from posthog.hogql_queries.insights.funnels.test.test_funnel_correlation_actors import BaseTestFunnelCorrelationActors
from posthog.hogql_queries.insights.funnels.test.test_funnel_udf import use_udf_funnel_flag_side_effect


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestFunnelCorrelationsActorsUDF(BaseTestFunnelCorrelationActors):
    __test__ = True
