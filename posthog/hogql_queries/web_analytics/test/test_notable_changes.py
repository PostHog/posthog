from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.schema import CompareFilter, DateRange, HogQLQueryModifiers, WebNotableChangesQuery

from posthog.hogql_queries.web_analytics.notable_changes import WebNotableChangesQueryRunner


@snapshot_clickhouse_queries
class TestWebNotableChangesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def _run_query(self, query: WebNotableChangesQuery):
        runner = WebNotableChangesQueryRunner(
            team=self.team,
            query=query,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True),
        )
        return runner.calculate()

    def _create_query(self, **kwargs) -> WebNotableChangesQuery:
        return WebNotableChangesQuery(
            dateRange=kwargs.get("dateRange", DateRange(date_from="-7d")),
            properties=kwargs.get("properties", []),
            compareFilter=kwargs.get("compareFilter", CompareFilter(compare=True)),
            filterTestAccounts=kwargs.get("filterTestAccounts", False),
            limit=kwargs.get("limit", 8),
        )

    def test_empty_results_without_preaggregated(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = self._create_query()
            runner = WebNotableChangesQueryRunner(
                team=self.team,
                query=query,
                modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=False),
            )
            response = runner.calculate()
            self.assertEqual(response.results, [])
            self.assertFalse(response.usedPreAggregatedTables)

    def test_scoring_high_traffic_high_change_ranks_above_low_traffic(self):
        runner = WebNotableChangesQueryRunner(
            team=self.team,
            query=self._create_query(),
        )
        results = [
            ["Page", "/popular", 1000, 500],
            ["Page", "/niche", 20, 10],
            ["Referrer", "google.com", 800, 700],
        ]
        scored = runner._score_results(results)

        self.assertEqual(len(scored), 3)
        self.assertEqual(scored[0].dimension_value, "/popular")
        self.assertTrue(scored[1].impact_score > scored[2].impact_score)

    def test_minimum_traffic_filtering(self):
        runner = WebNotableChangesQueryRunner(
            team=self.team,
            query=self._create_query(),
        )
        results = [
            ["Page", "/popular", 100, 50],
            ["Page", "/tiny", 3, 2],
        ]
        scored = runner._score_results(results)
        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].dimension_value, "/popular")

    def test_zero_previous_visitors(self):
        runner = WebNotableChangesQueryRunner(
            team=self.team,
            query=self._create_query(),
        )
        results = [
            ["Page", "/new-page", 50, 0],
        ]
        scored = runner._score_results(results)
        self.assertEqual(len(scored), 1)
        self.assertLessEqual(scored[0].percent_change, 10.0)

    def test_limit_applied(self):
        runner = WebNotableChangesQueryRunner(
            team=self.team,
            query=self._create_query(limit=2),
        )
        results = [["Page", f"/page-{i}", 100 + i * 50, 100] for i in range(5)]
        scored = runner._score_results(results)
        self.assertEqual(len(scored), 5)

    def test_all_dimensions_empty(self):
        runner = WebNotableChangesQueryRunner(
            team=self.team,
            query=self._create_query(),
        )
        results = []
        scored = runner._score_results(results)
        self.assertEqual(len(scored), 0)

    def test_percent_change_calculation(self):
        runner = WebNotableChangesQueryRunner(
            team=self.team,
            query=self._create_query(),
        )
        results = [
            ["Device", "Mobile", 75, 100],
        ]
        scored = runner._score_results(results)
        self.assertEqual(len(scored), 1)
        self.assertAlmostEqual(scored[0].percent_change, -0.25, places=2)
