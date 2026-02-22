from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

LINEAR_IGNORED_STATE_TYPES = ("completed", "cancelled")

LINEAR_SUMMARIZATION_PROMPT = """Summarize this Linear issue into a concise description for semantic search.
Capture the core problem or request, the product area affected, and key context like error messages or what the user was doing when the issue occurred.
Strip raw logs, full stack traces, and large code blocks — but keep specific error messages and high-level reproduction context if they clarify the issue.
Keep the summary under {max_length} characters. Respond with only the summary text.

<issue>
{description}
</issue>
"""

LINEAR_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a Linear issue, determine if it contains actionable product feedback.

An issue is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem or regression
- A question about how to use the product
- A gap or error in documentation that caused confusion
- and similar cases

An issue is NOT_ACTIONABLE if it is:
- A meta/tracking issue with no feedback (release checklists, sprint trackers)
- A duplicate that only says "same as X" with no new information
- An internal housekeeping task (dependency bumps, CI config, infra maintenance)

When in doubt, classify as ACTIONABLE. Linear issues are filed intentionally, so err on the side of capturing the signal.

<issue>
{description}
</issue>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

REQUIRED_FIELDS = ("id", "title", "description")

EXTRA_FIELDS = (
    "url",
    "identifier",
    "number",
    "priority",
    "priorityLabel",
    "labels",
    "state",
    "team",
    "createdAt",
    "updatedAt",
)


def linear_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
        title = record["title"]
        description = record["description"]
    except KeyError as e:
        msg = f"Linear issue record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id)
        raise ValueError(msg) from e
    if not issue_id or not title:
        msg = f"Linear issue record has empty required field: id={issue_id!r}, title={title!r}"
        logger.exception(msg, record=record, team_id=team_id)
        raise ValueError(msg)
    if not description:
        return None
    return SignalEmitterOutput(
        source_product="linear",
        source_type="issue",
        source_id=str(issue_id),
        description=f"{title}\n{description}",
        weight=1.0,
        extra={k: v for k, v in record.items() if k in EXTRA_FIELDS},
    )


LINEAR_ISSUES_CONFIG = SignalSourceTableConfig(
    emitter=linear_issue_emitter,
    partition_field="createdAt",
    partition_field_is_datetime_string=True,
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause=None,
    max_records=100,
    first_sync_lookback_days=7,
    actionability_prompt=LINEAR_ACTIONABILITY_PROMPT,
    summarization_prompt=LINEAR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
