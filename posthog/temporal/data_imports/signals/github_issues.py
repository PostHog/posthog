import json
from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

GITHUB_IGNORED_STATES = ("closed",)

GITHUB_SUMMARIZATION_PROMPT = """Summarize this GitHub issue for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) that captures the core issue
2. A concise summary capturing the problem or request, the product area affected, and key context like error messages or what the user was doing when the issue occurred

Strip raw logs, full stack traces, and large code blocks — but keep specific error messages and high-level reproduction context if they clarify the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

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
- A meta/tracking issue with no substantive feedback — issues that contain only a title and a bare link or a short reminder without describing a problem, use case, or solution (release checklists, sprint trackers, experiment-to-do notes)
- A duplicate that only says "same as #X" with no new information

When in doubt, classify as ACTIONABLE. GitHub issues are filed intentionally, so err on the side of capturing the signal. However, if an issue clearly matches one of the NOT_ACTIONABLE categories above, classify it as NOT_ACTIONABLE regardless.

<issue>
{description}
</issue>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

REQUIRED_FIELDS = ("id", "title", "body")

EXTRA_FIELDS = ("html_url", "number", "labels", "created_at", "updated_at", "locked", "state")
# TODO: Add "comments", but they can be pretty heavy, so better to iterate on them later,
# either when adding weight-defining logic, or when we decide to include them into the description


def github_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
        title = record["title"]
        body = record["body"]
    except KeyError as e:
        msg = f"GitHub issue record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id or not title:
        msg = f"GitHub issue record has empty required field: id={issue_id!r}, title={title!r}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg)
    if not body:
        logger.info(
            "Ignoring GitHub issue without a body", record=record, team_id=team_id, signals_type="data-import-signals"
        )
        return None
    return SignalEmitterOutput(
        source_product="github",
        source_type="issue",
        source_id=str(issue_id),
        description=f"{title}\n{body}",
        weight=1.0,
        extra=_build_extra(record),
    )


def _build_extra(record: dict[str, Any]) -> dict[str, Any]:
    extra = {k: v for k, v in record.items() if k in EXTRA_FIELDS}
    raw_labels = extra.get("labels")
    if raw_labels is None:
        extra["labels"] = []
    elif isinstance(raw_labels, str):
        try:
            parsed = json.loads(raw_labels)
        except (json.JSONDecodeError, TypeError) as e:
            msg = f"GitHub issue labels field is not valid JSON: {raw_labels!r}"
            logger.exception(msg, record=record, signals_type="data-import-signals")
            raise ValueError(msg) from e
        if not isinstance(parsed, list):
            msg = f"GitHub issue labels field is not a JSON array: {raw_labels!r}"
            logger.exception(msg, record=record, signals_type="data-import-signals")
            raise ValueError(msg)
        extra["labels"] = [label["name"] for label in parsed if isinstance(label, dict) and "name" in label]
    else:
        msg = f"GitHub issue labels field has unexpected type {type(raw_labels).__name__}: {raw_labels!r}"
        logger.exception(msg, record=record, signals_type="data-import-signals")
        raise ValueError(msg)
    return extra


GITHUB_ISSUES_CONFIG = SignalSourceTableConfig(
    emitter=github_issue_emitter,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause=f"state NOT IN ({', '.join(repr(s) for s in GITHUB_IGNORED_STATES)})",
    max_records=1000,
    first_sync_lookback_days=90,
    actionability_prompt=GITHUB_ACTIONABILITY_PROMPT,
    summarization_prompt=GITHUB_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
