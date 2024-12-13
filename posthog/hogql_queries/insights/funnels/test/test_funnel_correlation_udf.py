from unittest.mock import Mock, patch

from posthog.hogql_queries.insights.funnels.test.test_funnel_correlation import BaseTestClickhouseFunnelCorrelation
from posthog.hogql_queries.insights.funnels.test.test_funnel_udf import use_udf_funnel_flag_side_effect


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestClickhouseFunnelCorrelationUDF(BaseTestClickhouseFunnelCorrelation):
    __test__ = True
