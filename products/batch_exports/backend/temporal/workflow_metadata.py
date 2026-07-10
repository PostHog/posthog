"""Helpers for the user metadata shown next to batch export workflows in the Temporal UI.

Temporal exposes a static summary (a one-line description), and per-run current
details (a markdown panel). These helpers build that content: the summary string,
the markdown links to a team's admin page and the worker logs, and the
``WorkflowDetails`` builder used to assemble the details panel.
"""

import re
import json
from urllib.parse import quote, urlencode

from django.conf import settings

import humanize

# Temporal caps the static summary at 200 bytes; longer values are rejected.
STATIC_SUMMARY_MAX_BYTES = 200


def humanize_interval(interval: str) -> str:
    """Phrase a batch export interval for display, e.g. "hour" -> "every hour"."""
    return interval if interval.startswith("every") else f"every {interval}"


def humanize_bytes(num_bytes: int) -> str:
    """Format a byte count for display, e.g. 1572864 -> "1.5 MiB"."""
    return humanize.naturalsize(num_bytes, binary=True)


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    """Truncate to at most max_bytes of UTF-8, appending an ellipsis, without splitting a character."""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    ellipsis = "…"
    budget = max_bytes - len(ellipsis.encode("utf-8"))
    return text.encode("utf-8")[:budget].decode("utf-8", errors="ignore") + ellipsis


def build_static_summary(destination_type: str, model: str, interval: str, *, is_backfill: bool = False) -> str:
    """Build the Temporal static_summary shown next to a workflow in the UI."""
    prefix = "Backfill batch export" if is_backfill else "Batch export"
    summary = f"{prefix} {model} {humanize_interval(interval)} to {destination_type}"
    return _truncate_to_bytes(summary, STATIC_SUMMARY_MAX_BYTES)


def build_team_admin_link(team_id: int) -> str:
    """Build a markdown link to a team's Django admin page.

    Shown in the Temporal UI as part of a workflow's user metadata details.
    """
    return f"[{team_id}]({settings.SITE_URL}/admin/posthog/team/{team_id}/change/)"


def build_logs_link(workflow_id: str) -> str | None:
    """Build a markdown link to worker logs for a batch export workflow.

    Shown in the Temporal UI as part of a workflow's user metadata details.
    Returns None if TEMPORAL_LOGS_PROJECT_ID is not configured.
    """
    project_id = settings.TEMPORAL_LOGS_PROJECT_ID
    if not project_id:
        return None

    base_url = f"{settings.SITE_URL}/project/{project_id}/logs"
    filter_group = json.dumps(
        {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "workflow_id",
                            "value": [workflow_id],
                            "operator": "exact",
                            "type": "log_attribute",
                        }
                    ],
                }
            ],
        }
    )
    query_string = urlencode(
        {
            "serviceNames": json.dumps(["temporal-worker-batch-exports"]),
            "filterGroup": filter_group,
            "dateRange": json.dumps({"date_from": "-1d", "date_to": None}),
        },
        quote_via=quote,
    )
    return f"[View logs in PostHog]({base_url}?{query_string})"


class WorkflowDetails:
    """Builds the markdown for a Temporal workflow's current details panel.

    Rows render as blank-line-separated lines, with an optional footer (e.g. a
    logs link) always rendered last. Rows with a ``None`` value are skipped, so
    optional fields can be added unconditionally. Every method returns a new
    instance, so a base set of rows can be reused across multiple
    ``set_current_details`` calls without accumulating.
    """

    def __init__(self, footer: str | None = None, rows: tuple[str, ...] = ()) -> None:
        self._footer = footer
        self._rows = rows

    def add(self, label: str, value: object | None) -> "WorkflowDetails":
        """Append a ``label: value`` row, or nothing if ``value`` is None."""
        if value is None:
            return self
        return WorkflowDetails(self._footer, (*self._rows, f"{label}: {value}"))

    def text(self, value: str | None) -> "WorkflowDetails":
        """Append a free-form line (no label), or nothing if ``value`` is None."""
        if value is None:
            return self
        return WorkflowDetails(self._footer, (*self._rows, value))

    def code_block(self, label: str, value: object | None) -> "WorkflowDetails":
        """Append a ``label`` followed by ``value`` in a fenced code block, or nothing if None.

        Used for code blocks, but also, untrusted, potentially multi-line values (e.g. destination
        error text) so the Temporal UI does not render them as markdown. The fence is one backtick
        longer than the longest backtick run in the value, so the value cannot close the block early
        and escape it.
        """
        if value is None:
            return self
        text = str(value)
        longest_backtick_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
        fence = "`" * max(3, longest_backtick_run + 1)
        return WorkflowDetails(self._footer, (*self._rows, f"{label}:\n{fence}\n{text}\n{fence}"))

    def render(self) -> str:
        parts = self._rows if self._footer is None else (*self._rows, self._footer)
        return "\n\n".join(parts)
