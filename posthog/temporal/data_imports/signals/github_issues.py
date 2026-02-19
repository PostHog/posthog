from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

GITHUB_IGNORED_STATES = ("closed",)

GITHUB_SUMMARIZATION_PROMPT = """Summarize this GitHub issue into a concise description for semantic search.
Capture the core problem or request, the product area affected, and key context like error messages or what the user was doing when the issue occurred.
Strip raw logs, full stack traces, and large code blocks — but keep specific error messages and high-level reproduction context if they clarify the issue.
Keep the summary under {max_length} characters. Respond with only the summary text.

<issue>
{description}
</issue>
"""

GITHUB_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a GitHub issue, determine if it contains actionable product feedback.

An issue is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem or regression
- A self-hosted deployment or configuration problem
- A question about how to use the product
- A gap or error in documentation that caused confusion
- and similar cases

An issue is NOT_ACTIONABLE if it is:
- A bot-generated issue (dependency bumps, stale-bot closures, CI notifications, release automation)
- Spam, abuse, or profanity with no real feedback
- A meta/tracking issue with no feedback (release checklists, sprint trackers)
- A duplicate that only says "same as #X" with no new information

When in doubt, classify as ACTIONABLE. GitHub issues are filed intentionally, so err on the side of capturing the signal.

<issue>
{description}
</issue>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

REQUIRED_FIELDS = ("id", "title", "body")

EXTRA_FIELDS = ("html_url", "number", "labels", "created_at", "updated_at", "locked", "state")
# TODO: Add "comments", but they can be pretty heavy, so better to iterate on them later,
# either when adding weight-defining logic, or when we decide to include them into the description


def github_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    issue_id = record.get("id")
    title = record.get("title")
    if not issue_id or not title:
        logger.warning(
            f"Not enough meaningful data to emit a signal for issue {issue_id}",
            record=record,
            signals_type="github_issue",
        )
        return None
    body = record.get("body")
    signal_description = title
    if body:
        signal_description += f"\n{body}"
    return SignalEmitterOutput(
        source_type="github_issue",
        source_id=str(issue_id),
        description=signal_description,
        weight=1.0,
        extra={k: v for k, v in record.items() if k in EXTRA_FIELDS},
    )


GITHUB_ISSUES_CONFIG = SignalSourceTableConfig(
    emitter=github_issue_emitter,
    partition_field="created_at",
    partition_field_is_string=True,
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause=f"state NOT IN ({', '.join(repr(s) for s in GITHUB_IGNORED_STATES)})",
    max_records=100,
    first_sync_lookback_days=7,
    actionability_prompt=GITHUB_ACTIONABILITY_PROMPT,
    summarization_prompt=GITHUB_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
