from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import WebOverviewQuery
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestWebOverviewQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_runner(self, query: WebOverviewQuery) -> WebOverviewQueryRunner:
        return WebOverviewQueryRunner(team=self.team, query=query)

    def test_no_crash_when_no_data(self):
        response = self._create_runner(WebOverviewQuery(kind="WebOverviewQuery", properties=[])).calculate()
        self.assertEqual(5, len(response.results))
