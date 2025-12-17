from typing import Literal

from pydantic import BaseModel

from posthog.schema import ErrorTrackingQuery, OrderBy1

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.sync import database_sync_to_async

from ee.hogai.utils.prompt import format_prompt_string

from .prompts import ERROR_TRACKING_FILTERS_RESULT_TEMPLATE, ERROR_TRACKING_ISSUE_RESULT_TEMPLATE

ErrorTrackingStatus = Literal["active", "resolved", "suppressed"]


class ErrorTrackingIssueResult(BaseModel):
    """Normalized result for an error tracking issue."""

    id: str | None = None
    name: str | None = None
    description: str | None = None
    status: str | None = None
    occurrences: float | None = None
    users: float | None = None
    sessions: float | None = None
    first_seen: str | None = None
    last_seen: str | None = None


class ErrorTrackingFiltersContext:
    """
    Context class for error tracking filters query execution and formatting.

    Consolidates the logic for querying ErrorTrackingQuery and extracting issue results.
    Used by both read_data tool and error tracking max_tools.
    """

    def __init__(
        self,
        team: Team,
        status: ErrorTrackingStatus | None = None,
        search_query: str | None = None,
        date_from: str = "-7d",
        date_to: str | None = None,
        order_by: OrderBy1 = OrderBy1.LAST_SEEN,
        filter_group: dict | None = None,
        filter_test_accounts: bool = False,
        limit: int = 25,
    ):
        self.team = team
        self.status = status
        self.search_query = search_query
        self.date_from = date_from
        self.date_to = date_to
        self.order_by = order_by
        self.filter_group = filter_group
        self.filter_test_accounts = filter_test_accounts
        self.limit = max(1, min(int(limit), 100))

    def _build_query(self) -> ErrorTrackingQuery:
        """Build the ErrorTrackingQuery from context parameters."""
        return ErrorTrackingQuery(
            dateRange={"date_from": self.date_from, "date_to": self.date_to},
            orderBy=self.order_by,
            volumeResolution=1,
            status=self.status,
            searchQuery=self.search_query,
            filterGroup=self.filter_group,
            filterTestAccounts=self.filter_test_accounts,
            withAggregations=True,
            limit=self.limit,
        )

    @database_sync_to_async
    def _execute_query(self) -> list[ErrorTrackingIssueResult]:
        """Execute the query and return formatted results."""
        query = self._build_query()

        try:
            runner = get_query_runner(query, team=self.team)
            response = runner.calculate()

            issues_out: list[ErrorTrackingIssueResult] = []
            if response.results:
                for issue in response.results:
                    agg = issue.aggregations if hasattr(issue, "aggregations") and issue.aggregations else None
                    issues_out.append(
                        ErrorTrackingIssueResult(
                            id=str(issue.id) if hasattr(issue, "id") else None,
                            name=issue.name if hasattr(issue, "name") else None,
                            description=issue.description if hasattr(issue, "description") else None,
                            status=issue.status if hasattr(issue, "status") else None,
                            occurrences=agg.occurrences if agg else None,
                            users=agg.users if agg else None,
                            sessions=agg.sessions if agg else None,
                            first_seen=str(issue.first_seen)
                            if hasattr(issue, "first_seen") and issue.first_seen
                            else None,
                            last_seen=str(issue.last_seen) if hasattr(issue, "last_seen") and issue.last_seen else None,
                        )
                    )
            return issues_out
        except Exception:
            return []

    async def execute(self) -> list[ErrorTrackingIssueResult]:
        """Execute the query and return raw results."""
        return await self._execute_query()

    async def execute_and_format(
        self,
        prompt_template: str = ERROR_TRACKING_FILTERS_RESULT_TEMPLATE,
    ) -> str:
        """Execute query and format results using a template."""
        issues = await self._execute_query()

        return format_prompt_string(
            prompt_template,
            template_format="mustache",
            count=len(issues),
            limit=self.limit if len(issues) >= self.limit else None,
            issues=[issue.model_dump() for issue in issues],
        )


class ErrorTrackingIssueContext:
    """
    Context class for single error tracking issue queries.

    Fetches aggregations and metadata for a specific issue by ID.
    """

    def __init__(
        self,
        team: Team,
        issue_id: str,
        date_from: str = "-30d",
        date_to: str | None = None,
    ):
        self.team = team
        self.issue_id = issue_id
        self.date_from = date_from
        self.date_to = date_to

    def _build_query(self) -> ErrorTrackingQuery:
        """Build the ErrorTrackingQuery for a specific issue."""
        return ErrorTrackingQuery(
            issueId=self.issue_id,
            dateRange={"date_from": self.date_from, "date_to": self.date_to},
            orderBy=OrderBy1.LAST_SEEN,
            volumeResolution=1,
            withAggregations=True,
            filterTestAccounts=False,
        )

    @database_sync_to_async
    def _execute_query(self) -> ErrorTrackingIssueResult | None:
        """Execute the query and return aggregations for the issue."""
        query = self._build_query()

        try:
            runner = get_query_runner(query, team=self.team)
            response = runner.calculate()

            if not response.results or len(response.results) == 0:
                return None

            result = response.results[0]
            agg = result.aggregations if hasattr(result, "aggregations") and result.aggregations else None

            return ErrorTrackingIssueResult(
                id=str(result.id) if hasattr(result, "id") else self.issue_id,
                name=result.name if hasattr(result, "name") else None,
                description=result.description if hasattr(result, "description") else None,
                status=result.status if hasattr(result, "status") else None,
                occurrences=agg.occurrences if agg else None,
                users=agg.users if agg else None,
                sessions=agg.sessions if agg else None,
                first_seen=str(result.first_seen) if hasattr(result, "first_seen") and result.first_seen else None,
                last_seen=str(result.last_seen) if hasattr(result, "last_seen") and result.last_seen else None,
            )
        except Exception:
            return None

    async def execute(self) -> ErrorTrackingIssueResult | None:
        """Execute the query and return raw results."""
        return await self._execute_query()

    async def execute_and_format(
        self,
        prompt_template: str = ERROR_TRACKING_ISSUE_RESULT_TEMPLATE,
    ) -> str | None:
        """Execute query and format results using a template."""
        issue = await self._execute_query()

        if not issue:
            return None

        return format_prompt_string(
            prompt_template,
            template_format="mustache",
            **issue.model_dump(),
        )
