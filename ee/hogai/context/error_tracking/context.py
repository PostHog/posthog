import json

from posthog.schema import DateRange, ErrorTrackingQuery, OrderBy1

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.error_tracking.backend.models import ErrorTrackingIssue

from .prompts import ERROR_TRACKING_ISSUE_CONTEXT_TEMPLATE


class ErrorTrackingIssueContext:
    """
    Context class for error tracking issues used across the assistant.

    Provides methods to fetch issue data and format it for AI consumption.
    This class is used by the ReadDataTool to provide issue context without
    invoking nested LLM calls.
    """

    def __init__(
        self,
        team: Team,
        issue_id: str,
        issue_name: str | None = None,
    ):
        self._team = team
        self._issue_id = issue_id
        self._issue_name = issue_name

    async def aget_issue(self) -> ErrorTrackingIssue | None:
        """Fetch the issue from the database using async."""
        try:
            return await ErrorTrackingIssue.objects.aget(id=self._issue_id, team=self._team)
        except ErrorTrackingIssue.DoesNotExist:
            return None

    async def aget_first_event(self) -> dict | None:
        """Fetch the first event for the issue to get stack trace data."""
        return await database_sync_to_async(self._get_first_event_sync)()

    def _get_first_event_sync(self) -> dict | None:
        """Synchronous implementation of get_first_event."""
        query = ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            issueId=self._issue_id,
            dateRange=DateRange(date_from="all"),
            orderBy=OrderBy1.FIRST_SEEN,
            limit=1,
            volumeResolution=1,
            withAggregations=False,
            withFirstEvent=True,
            withLastEvent=False,
        )

        runner = get_query_runner(query, self._team)
        result = runner.calculate()

        if result.results and len(result.results) > 0:
            first_result = result.results[0]
            if hasattr(first_result, "model_dump"):
                first_result = first_result.model_dump()
            if isinstance(first_result, dict):
                return first_result.get("first_event")
            return None

        return None

    def format_stacktrace(self, event: dict | None) -> str | None:
        """Format the exception list into a readable stack trace string."""
        if not event:
            return None

        properties = event.get("properties", {})
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except json.JSONDecodeError:
                return None
        exception_list = properties.get("$exception_list", [])

        if not exception_list:
            return None

        lines: list[str] = []

        for i, exception in enumerate(exception_list):
            exc_type = exception.get("type", "Unknown")
            exc_value = exception.get("value", "")

            lines.append(f"Exception {i + 1}: {exc_type}")
            if exc_value:
                lines.append(f"Message: {exc_value}")
            lines.append("")

            stacktrace = exception.get("stacktrace", {})
            frames = stacktrace.get("frames", []) if stacktrace else []

            if frames:
                lines.append("Stack trace (most recent call last):")
                for frame in reversed(frames):
                    in_app = frame.get("in_app", False)
                    marker = "[IN-APP]" if in_app else ""

                    filename = frame.get("source", "unknown")
                    lineno = frame.get("line", "?")
                    colno = frame.get("column")
                    function = frame.get("resolved_name") or frame.get("mangled_name") or "<unknown>"

                    location = f"{filename}:{lineno}"
                    if colno:
                        location += f":{colno}"

                    lines.append(f"  {marker} at {function} ({location})")

                    context_line = frame.get("context_line")
                    if context_line:
                        lines.append(f"       > {context_line.strip()}")

                lines.append("")

        return "\n".join(lines) if lines else None

    async def execute_and_format(self) -> str:
        """
        Execute the context gathering and format results for AI consumption.

        Returns a formatted string with all issue context including stacktrace.
        """
        issue = await self.aget_issue()
        if issue is None:
            return f"Error tracking issue with ID '{self._issue_id}' not found."

        issue_name = self._issue_name or issue.name or f"Issue {self._issue_id}"

        first_event = await self.aget_first_event()
        if first_event is None:
            return f"No events found for issue '{issue_name}'. Cannot provide stack trace data."

        stacktrace = self.format_stacktrace(first_event)
        if not stacktrace:
            return f"No stack trace available for issue '{issue_name}'."

        return ERROR_TRACKING_ISSUE_CONTEXT_TEMPLATE.format(
            issue_id=self._issue_id,
            issue_name=issue_name,
            issue_status=issue.status,
            issue_description=issue.description or "No description available.",
            stacktrace=stacktrace,
        )
