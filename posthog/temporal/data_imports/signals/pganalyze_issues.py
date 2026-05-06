import json
from typing import Any

from structlog import get_logger

from posthog.temporal.data_imports.signals.fetchers.data_warehouse import data_warehouse_record_fetcher
from posthog.temporal.data_imports.signals.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

PGANALYZE_SUMMARIZATION_PROMPT = """Summarize this pganalyze database performance finding for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) capturing the core finding (e.g. "Missing index on users.email")
2. A concise summary capturing the database, the kind of issue (slow query, missing index, vacuum problem, log event, etc.), the affected query or relation if mentioned, and any suggested remediation

Strip raw query plans, large SQL excerpts, and per-row metrics — but keep specific table/index names, error messages, and the type of operation involved if they clarify the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<finding>
{description}
</finding>
"""

PGANALYZE_ACTIONABILITY_PROMPT = """You are a database performance analyst. Given a pganalyze finding (an "issue" surfaced by a pganalyze check — covering missing indexes, slow queries, vacuum problems, schema changes, log events, etc.), determine if it represents something engineers could address with code, schema, or configuration changes.

A finding is ACTIONABLE if it describes:
- A missing or unused index recommendation
- A slow or regressed query that could be optimized, rewritten, or supported by an index
- A vacuum, autovacuum, or bloat problem with a clear remediation
- A schema or configuration issue (e.g. fillfactor, work_mem, shared_buffers) with concrete advice
- A replication, checkpoint, or WAL problem that engineers can address
- A log event, error, or deadlock that engineers can fix at the application or database layer
- A pganalyze check failure that points to specific tables, queries, or settings

A finding is NOT_ACTIONABLE if it is:
- Purely informational with no recommended action ("snapshot succeeded", "collector started")
- A transient or self-resolving condition with no remediation
- A duplicate of a higher-severity finding already represented elsewhere
- A noise check that fires on every snapshot regardless of severity

When in doubt, classify as ACTIONABLE — pganalyze findings are usually worth a look. Only mark NOT_ACTIONABLE if the finding clearly has no engineering follow-up.

<finding>
{description}
</finding>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""


REQUIRED_FIELDS = ("id", "description")

EXTRA_FIELDS = (
    "severity",
    "references",
    "database_id",
    "server_human_id",
    "server_name",
    "synced_at",
)


def _references_to_url_and_title(record: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_refs = record.get("references")
    if raw_refs is None:
        return None, None
    if isinstance(raw_refs, str):
        try:
            parsed: Any = json.loads(raw_refs)
        except (json.JSONDecodeError, TypeError) as e:
            msg = f"pganalyze issue references field is not valid JSON: {raw_refs!r}"
            logger.exception(msg, record=record, signals_type="data-import-signals")
            raise ValueError(msg) from e
    else:
        parsed = raw_refs
    if not isinstance(parsed, list):
        msg = f"pganalyze issue references field is not a list: {parsed!r}"
        logger.exception(msg, record=record, signals_type="data-import-signals")
        raise ValueError(msg)
    if not parsed:
        return None, None
    first = parsed[0] if isinstance(parsed[0], dict) else {}
    return first.get("url"), first.get("name")


def pganalyze_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
        description = record["description"]
    except KeyError as e:
        msg = f"pganalyze issue record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id or not description:
        msg = f"pganalyze issue record has empty required field: id={issue_id!r}, description={description!r}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg)

    severity = record.get("severity") or "unknown"
    server_name = record.get("server_name") or record.get("server_human_id") or "unknown server"
    _, ref_name = _references_to_url_and_title(record)

    title_parts = [f"[{severity}]", server_name]
    if ref_name:
        title_parts.append(f"— {ref_name}")
    signal_description = f"{' '.join(title_parts)}\n{description}"

    return SignalEmitterOutput(
        source_product="pganalyze",
        source_type="issue",
        source_id=str(issue_id),
        description=signal_description,
        weight=1.0,
        extra=_build_extra(record),
    )


def _build_extra(record: dict[str, Any]) -> dict[str, Any]:
    extra = {k: v for k, v in record.items() if k in EXTRA_FIELDS}
    raw_refs = extra.get("references")
    if raw_refs is None:
        extra["references"] = []
    elif isinstance(raw_refs, str):
        try:
            parsed: Any = json.loads(raw_refs)
        except (json.JSONDecodeError, TypeError) as e:
            msg = f"pganalyze issue references field is not valid JSON: {raw_refs!r}"
            logger.exception(msg, record=record, signals_type="data-import-signals")
            raise ValueError(msg) from e
        if not isinstance(parsed, list):
            msg = f"pganalyze issue references field is not a JSON array: {raw_refs!r}"
            logger.exception(msg, record=record, signals_type="data-import-signals")
            raise ValueError(msg)
        extra["references"] = parsed
    elif not isinstance(raw_refs, list):
        msg = f"pganalyze issue references field has unexpected type {type(raw_refs).__name__}: {raw_refs!r}"
        logger.exception(msg, record=record, signals_type="data-import-signals")
        raise ValueError(msg)
    return extra


PGANALYZE_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="pganalyze",
    source_type="issue",
    emitter=pganalyze_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="synced_at",
    partition_field_is_datetime_string=True,
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    max_records=200,
    first_sync_lookback_days=30,
    actionability_prompt=PGANALYZE_ACTIONABILITY_PROMPT,
    summarization_prompt=PGANALYZE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
