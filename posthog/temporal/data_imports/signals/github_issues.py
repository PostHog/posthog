from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

GITHUB_IGNORED_STATES = ("closed",)

GITHUB_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a GitHub issue, determine if it contains actionable product feedback.

An issue is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem or regression

An issue is NOT_ACTIONABLE if it is:
- A bot-generated issue (dependency bumps, automated security alerts, CI notifications)
- Spam, abuse, or profanity with no real feedback
- A duplicate of another issue with no additional context
- A generic "how do I" question answerable by docs
- A "works for me" or "cannot reproduce" report with no actionable detail
- A stale issue with no meaningful content

Issue:
```
{description}
```

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

REQUIRED_FIELDS = ("id", "title", "body", "state")

EXTRA_FIELDS = ("html_url", "number", "labels", "created_at", "updated_at", "comments", "locked")


def _extract_extra(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k in EXTRA_FIELDS}


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
    state = record.get("state")
    signal_description = f"New GitHub issue: {title}."
    if body:
        signal_description += f"\nDescription: {body}."
    if state:
        signal_description += f"\nState: {state}."
    return SignalEmitterOutput(
        source_type="github_issue",
        source_id=str(issue_id),
        description=signal_description,
        weight=1.0,
        extra=_extract_extra(record),
    )


GITHUB_ISSUES_CONFIG = SignalSourceTableConfig(
    emitter=github_issue_emitter,
    partition_field="created_at",
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause=f"state NOT IN {GITHUB_IGNORED_STATES!r}",
    max_records=100,
    first_sync_lookback_days=7,
    actionability_prompt=GITHUB_ACTIONABILITY_PROMPT,
)
