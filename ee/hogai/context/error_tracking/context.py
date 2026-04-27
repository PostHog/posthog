import json
from typing import Any
from uuid import UUID

from posthog.schema import DateRange, ErrorTrackingOrderBy, ErrorTrackingQuery

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.error_tracking.backend.facade import (
    api as error_tracking_api,
    types as error_tracking_types,
)

from .prompts import (
    BREADCRUMBS_SECTION_TEMPLATE,
    ERROR_TRACKING_ISSUE_CONTEXT_TEMPLATE,
    REPLAY_SECTION_TEMPLATE,
    THIRD_PARTY_NOISE_WARNING,
)

EXTENSION_SCHEMES = ("chrome-extension://", "moz-extension://", "safari-extension://", "safari-web-extension://")
THIRD_PARTY_SCRIPT_ERROR_VALUES = {"Script error.", "Script error"}
MAX_BREADCRUMBS = 10


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

    def _get_issue_sync(self) -> error_tracking_types.ErrorTrackingIssue | None:
        try:
            issue_id = UUID(self._issue_id)
        except ValueError:
            return None

        try:
            return error_tracking_api.get_issue(issue_id=issue_id, team_id=self._team.id)
        except error_tracking_api.IssueNotFoundError:
            return None

    async def aget_issue(self) -> error_tracking_types.ErrorTrackingIssue | None:
        """Fetch the issue from the error tracking facade using async."""
        return await database_sync_to_async(self._get_issue_sync)()

    async def aget_first_event(self) -> dict | None:
        """Fetch the first event for the issue to get stack trace data."""
        return await database_sync_to_async(self._get_first_event_sync)()

    def _get_first_event_sync(self) -> dict | None:
        """Synchronous implementation of get_first_event."""
        query = ErrorTrackingQuery(
            kind="ErrorTrackingQuery",
            issueId=self._issue_id,
            dateRange=DateRange(date_from="all"),
            orderBy=ErrorTrackingOrderBy.FIRST_SEEN,
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

    @staticmethod
    def _get_event_properties(event: dict | None) -> dict[str, Any]:
        if not event:
            return {}
        properties = event.get("properties", {})
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except json.JSONDecodeError:
                return {}
        return properties if isinstance(properties, dict) else {}

    @classmethod
    def _detect_third_party_noise(cls, properties: dict[str, Any]) -> str | None:
        """Return a human-readable reason if the event is likely third-party noise."""
        exception_list = properties.get("$exception_list", []) or []
        if exception_list:
            first = exception_list[0] or {}
            value = first.get("value") if isinstance(first, dict) else None
            if isinstance(value, str) and value.strip() in THIRD_PARTY_SCRIPT_ERROR_VALUES:
                return "a cross-origin 'Script error.' with no usable stack frames"

            stacktrace = first.get("stacktrace") if isinstance(first, dict) else None
            frames = stacktrace.get("frames", []) if isinstance(stacktrace, dict) else []
            if frames and all(cls._frame_is_extension(frame) for frame in frames):
                return "frames from a browser extension (chrome-extension:// / moz-extension://)"
        return None

    @staticmethod
    def _frame_is_extension(frame: dict[str, Any]) -> bool:
        if not isinstance(frame, dict):
            return False
        for key in ("source", "abs_path", "filename"):
            value = frame.get(key)
            if isinstance(value, str) and value.startswith(EXTENSION_SCHEMES):
                return True
        return False

    @staticmethod
    def _format_event_context(properties: dict[str, Any]) -> str:
        """Format key environment properties for the LLM."""

        def concat(*keys: str) -> str | None:
            parts = [str(properties[key]) for key in keys if properties.get(key)]
            return " ".join(parts) if parts else None

        rows: list[tuple[str, str | None]] = [
            ("URL", properties.get("$current_url")),
            ("Route name", properties.get("$pathname")),
            ("Browser", concat("$browser", "$browser_version")),
            ("OS", concat("$os", "$os_version")),
            ("Library", concat("$lib", "$lib_version")),
            ("App version", properties.get("$app_version")),
            ("Device type", properties.get("$device_type")),
            ("Level", properties.get("$level")),
            ("Locale", properties.get("$browser_language")),
        ]

        lines = [f"- **{label}:** {value}" for label, value in rows if value]
        return "\n".join(lines) if lines else "- _No environment properties available._"

    @staticmethod
    def _format_breadcrumbs(properties: dict[str, Any]) -> str | None:
        """Render breadcrumbs (Sentry-compatible) so the LLM can see what the user did before the error."""
        candidates: list[Any] = []
        for key in ("$exception_breadcrumbs", "$breadcrumbs", "$sentry_breadcrumbs"):
            value = properties.get(key)
            if isinstance(value, list):
                candidates = value
                break
            if isinstance(value, dict):
                values = value.get("values")
                if isinstance(values, list):
                    candidates = values
                    break
        if not candidates:
            return None

        rendered: list[str] = []
        for crumb in candidates[-MAX_BREADCRUMBS:]:
            if not isinstance(crumb, dict):
                continue
            timestamp = crumb.get("timestamp") or ""
            category = crumb.get("category") or crumb.get("type") or "event"
            message = crumb.get("message") or crumb.get("data", {}) or ""
            if isinstance(message, dict):
                message = json.dumps(message, default=str)
            rendered.append(f"- [{timestamp}] ({category}) {message}".rstrip())

        return "\n".join(rendered) if rendered else None

    def format_stacktrace(self, event: dict | None) -> str | None:
        """Format the exception list into a readable stack trace string."""
        if not event:
            return None

        properties = self._get_event_properties(event)
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
                    is_extension = self._frame_is_extension(frame)
                    if is_extension:
                        marker = "[EXTENSION]"
                    elif in_app:
                        marker = "[IN-APP]"
                    else:
                        marker = ""

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

        properties = self._get_event_properties(first_event)
        event_context = self._format_event_context(properties)
        breadcrumbs = self._format_breadcrumbs(properties)
        breadcrumbs_section = (
            BREADCRUMBS_SECTION_TEMPLATE.format(breadcrumbs=breadcrumbs) if breadcrumbs else ""
        )
        session_id = properties.get("$session_id")
        replay_section = REPLAY_SECTION_TEMPLATE.format(session_id=session_id) if session_id else ""

        noise_reason = self._detect_third_party_noise(properties)
        noise_warning = THIRD_PARTY_NOISE_WARNING.format(noise_reason=noise_reason) if noise_reason else ""

        return ERROR_TRACKING_ISSUE_CONTEXT_TEMPLATE.format(
            issue_id=self._issue_id,
            issue_name=issue_name,
            issue_status=issue.status,
            issue_description=issue.description or "No description available.",
            event_context=event_context,
            stacktrace=stacktrace,
            breadcrumbs_section=breadcrumbs_section,
            replay_section=replay_section,
            noise_warning=noise_warning,
        )
