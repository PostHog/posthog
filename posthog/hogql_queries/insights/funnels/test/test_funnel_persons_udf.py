from datetime import datetime

from unittest.mock import Mock, patch

from posthog.schema import ActorsQuery, DateRange, EventsNode, FunnelsActorsQuery, FunnelsFilter, FunnelsQuery

from posthog.constants import INSIGHT_FUNNELS
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import BaseTestFunnelPersons, get_actors
from posthog.hogql_queries.insights.funnels.test.test_funnel_udf import use_udf_funnel_flag_side_effect
from posthog.test.test_journeys import journeys_for


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

    def test_optional_funnel_step_actors_query(self):
        journeys_for(
            {
                "user_skips_optional_step": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 0, 0, 0)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 0, 2, 0)},
                ],
            },
            self.team,
        )

        funnels_query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step two", optionalInFunnel=True),
                EventsNode(event="step three"),
            ],
            dateRange=DateRange(
                date_from="2021-05-01 00:00:00",
                date_to="2021-05-07 00:00:00",
            ),
            funnelsFilter=FunnelsFilter(funnelWindowInterval=7, funnelWindowIntervalUnit="day"),
        )

        funnel_actors_query = FunnelsActorsQuery(
            source=funnels_query,
            funnelStep=3,
        )

        actors_query = ActorsQuery(
            source=funnel_actors_query,
            select=["id", "person"],
        )

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()
        results = response.results

        self.assertEqual(len(results), 1)

    def test_optional_funnel_step_dropoff_actors_query(self):
        journeys_for(
            {
                "user_does_step1_only": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 0, 0, 0)},
                ],
                "user_does_step1_and_2_only": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 0, 0, 0)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 0, 1, 0)},
                ],
                "user_does_all_steps": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1, 0, 0, 0)},
                    {"event": "step two", "timestamp": datetime(2021, 5, 1, 0, 1, 0)},
                    {"event": "step three", "timestamp": datetime(2021, 5, 1, 0, 2, 0)},
                ],
            },
            self.team,
        )

        funnels_query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step two", optionalInFunnel=True),
                EventsNode(event="step three"),
            ],
            dateRange=DateRange(
                date_from="2021-05-01 00:00:00",
                date_to="2021-05-07 00:00:00",
            ),
            funnelsFilter=FunnelsFilter(funnelWindowInterval=7, funnelWindowIntervalUnit="day"),
        )

        # Dropoff at step 3: users who did step 1 (required) but not step 3
        # This should include both users who skipped the optional step 2 and users who did it
        funnel_actors_query = FunnelsActorsQuery(
            source=funnels_query,
            funnelStep=-3,
        )

        actors_query = ActorsQuery(
            source=funnel_actors_query,
            select=["id", "person"],
        )

        response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()
        results = response.results

        # Should return 2 users: user_does_step1_only and user_does_step1_and_2_only
        self.assertEqual(len(results), 2)
