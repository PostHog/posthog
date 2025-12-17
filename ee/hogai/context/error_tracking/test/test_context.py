from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import OrderBy1

from ee.hogai.context.error_tracking.context import (
    ErrorTrackingFiltersContext,
    ErrorTrackingIssueContext,
    ErrorTrackingIssueResult,
)


class TestErrorTrackingFiltersContext(BaseTest):
    def test_initialization_with_defaults(self):
        context = ErrorTrackingFiltersContext(team=self.team)
        assert context.team == self.team
        assert context.status is None
        assert context.search_query is None
        assert context.date_from == "-7d"
        assert context.date_to is None
        assert context.order_by == OrderBy1.LAST_SEEN
        assert context.filter_group is None
        assert context.filter_test_accounts is False
        assert context.limit == 25

    def test_initialization_with_custom_values(self):
        context = ErrorTrackingFiltersContext(
            team=self.team,
            status="active",
            search_query="TypeError",
            date_from="-14d",
            date_to="-1d",
            order_by=OrderBy1.OCCURRENCES,
            filter_group={"type": "AND", "values": []},
            filter_test_accounts=True,
            limit=50,
        )
        assert context.status == "active"
        assert context.search_query == "TypeError"
        assert context.date_from == "-14d"
        assert context.date_to == "-1d"
        assert context.order_by == OrderBy1.OCCURRENCES
        assert context.filter_group == {"type": "AND", "values": []}
        assert context.filter_test_accounts is True
        assert context.limit == 50

    def test_limit_clamped_to_valid_range(self):
        context_low = ErrorTrackingFiltersContext(team=self.team, limit=0)
        assert context_low.limit == 1

        context_high = ErrorTrackingFiltersContext(team=self.team, limit=500)
        assert context_high.limit == 100

    def test_build_query(self):
        context = ErrorTrackingFiltersContext(
            team=self.team,
            status="resolved",
            search_query="NullPointer",
            date_from="-7d",
            date_to="-1d",
            order_by=OrderBy1.OCCURRENCES,
            filter_test_accounts=True,
            limit=10,
        )
        query = context._build_query()
        assert query.status == "resolved"
        assert query.searchQuery == "NullPointer"
        assert query.dateRange.date_from == "-7d"
        assert query.dateRange.date_to == "-1d"
        assert query.orderBy == OrderBy1.OCCURRENCES
        assert query.filterTestAccounts is True
        assert query.withAggregations is True
        assert query.limit == 10

    async def test_execute_returns_empty_list_on_exception(self):
        context = ErrorTrackingFiltersContext(team=self.team)

        with patch("ee.hogai.context.error_tracking.context.get_query_runner") as mock_runner:
            mock_runner.side_effect = Exception("Query failed")
            result = await context.execute()
            assert result == []

    async def test_execute_returns_issue_results(self):
        context = ErrorTrackingFiltersContext(team=self.team)

        mock_issue = MagicMock()
        mock_issue.id = "issue-123"
        mock_issue.name = "TypeError in app.js"
        mock_issue.description = "Test description"
        mock_issue.status = "active"
        mock_issue.first_seen = "2024-01-01T00:00:00Z"
        mock_issue.last_seen = "2024-01-15T00:00:00Z"
        mock_issue.aggregations = MagicMock()
        mock_issue.aggregations.occurrences = 100
        mock_issue.aggregations.users = 50
        mock_issue.aggregations.sessions = 75

        mock_response = MagicMock()
        mock_response.results = [mock_issue]

        with patch("ee.hogai.context.error_tracking.context.get_query_runner") as mock_runner:
            mock_runner.return_value.calculate.return_value = mock_response
            result = await context.execute()

            assert len(result) == 1
            assert isinstance(result[0], ErrorTrackingIssueResult)
            assert result[0].id == "issue-123"
            assert result[0].name == "TypeError in app.js"
            assert result[0].occurrences == 100
            assert result[0].users == 50


class TestErrorTrackingIssueContext(BaseTest):
    def test_initialization(self):
        context = ErrorTrackingIssueContext(team=self.team, issue_id="test-issue-id")
        assert context.team == self.team
        assert context.issue_id == "test-issue-id"
        assert context.date_from == "-30d"
        assert context.date_to is None

    def test_initialization_with_custom_dates(self):
        context = ErrorTrackingIssueContext(
            team=self.team,
            issue_id="test-issue-id",
            date_from="-7d",
            date_to="-1d",
        )
        assert context.date_from == "-7d"
        assert context.date_to == "-1d"

    def test_build_query(self):
        context = ErrorTrackingIssueContext(
            team=self.team,
            issue_id="test-issue-id",
            date_from="-14d",
        )
        query = context._build_query()
        assert query.issueId == "test-issue-id"
        assert query.dateRange.date_from == "-14d"
        assert query.dateRange.date_to is None
        assert query.withAggregations is True

    async def test_execute_returns_none_on_exception(self):
        context = ErrorTrackingIssueContext(team=self.team, issue_id="test-id")

        with patch("ee.hogai.context.error_tracking.context.get_query_runner") as mock_runner:
            mock_runner.side_effect = Exception("Query failed")
            result = await context.execute()
            assert result is None

    async def test_execute_returns_none_when_no_results(self):
        context = ErrorTrackingIssueContext(team=self.team, issue_id="nonexistent-id")

        mock_response = MagicMock()
        mock_response.results = []

        with patch("ee.hogai.context.error_tracking.context.get_query_runner") as mock_runner:
            mock_runner.return_value.calculate.return_value = mock_response
            result = await context.execute()
            assert result is None

    async def test_execute_returns_issue_result(self):
        context = ErrorTrackingIssueContext(team=self.team, issue_id="issue-123")

        mock_issue = MagicMock()
        mock_issue.id = "issue-123"
        mock_issue.name = "Critical Error"
        mock_issue.description = None
        mock_issue.status = "active"
        mock_issue.first_seen = "2024-01-01T00:00:00Z"
        mock_issue.last_seen = "2024-01-15T00:00:00Z"
        mock_issue.aggregations = MagicMock()
        mock_issue.aggregations.occurrences = 500
        mock_issue.aggregations.users = 200
        mock_issue.aggregations.sessions = 300

        mock_response = MagicMock()
        mock_response.results = [mock_issue]

        with patch("ee.hogai.context.error_tracking.context.get_query_runner") as mock_runner:
            mock_runner.return_value.calculate.return_value = mock_response
            result = await context.execute()

            assert isinstance(result, ErrorTrackingIssueResult)
            assert result.id == "issue-123"
            assert result.name == "Critical Error"
            assert result.occurrences == 500
            assert result.users == 200
            assert result.sessions == 300
