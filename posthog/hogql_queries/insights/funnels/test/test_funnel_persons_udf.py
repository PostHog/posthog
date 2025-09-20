from unittest.mock import Mock, patch

from posthog.constants import INSIGHT_FUNNELS
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import BaseTestFunnelPersons, get_actors
from posthog.hogql_queries.insights.funnels.test.test_funnel_udf import use_udf_funnel_flag_side_effect


@patch("posthoganalytics.feature_enabled", new=Mock(side_effect=use_udf_funnel_flag_side_effect))
class TestFunnelPersonsUDF(BaseTestFunnelPersons):
    __test__ = True

    @patch("posthog.hogql_queries.insights.funnels.funnel_udf.FunnelUDF.actor_query", return_value=None)
    def test_uses_udf(self, obj):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        self.assertRaises(Exception, lambda: get_actors(filters, self.team, funnel_step=1))
