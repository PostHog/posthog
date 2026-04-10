import json

from posthog.models import Team

from products.error_tracking.backend.facade import ErrorTrackingIssueContract, aget_issue, aget_issue_first_event

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

    async def aget_issue(self) -> ErrorTrackingIssueContract | None:
        """Fetch the issue through the Error tracking facade using async."""
        return await aget_issue(self._issue_id, self._team)

    async def aget_first_event(self) -> dict | None:
        """Fetch the first event for the issue to get stack trace data."""
        return await aget_issue_first_event(self._team, self._issue_id)

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
