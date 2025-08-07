from freezegun import freeze_time

from posthog.hogql_queries.error_tracking_issue_correlation_query_runner import ErrorTrackingIssueCorrelationQueryRunner
from posthog.schema import (
    ErrorTrackingIssueCorrelationQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)
from posthog.test.base import snapshot_clickhouse_queries


class TestErrorTrackingIssueCorrelationQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _calculate(
        self,
    ):
        return (
            ErrorTrackingIssueCorrelationQueryRunner(
                team=self.team,
                query=ErrorTrackingIssueCorrelationQuery(
                    kind="ErrorTrackingIssueCorrelationQuery",
                    events=["$pageview"],
                ),
            )
            .calculate()
            .model_dump()
        )

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_column_names(self):
        columns = self._calculate()["columns"]
        self.assertEqual(
            columns,
            [
                "event",
                "issue_ids",
                "both",
                "success_only",
                "exception_only",
                "neither",
            ],
        )
