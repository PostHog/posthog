"""Server-assembled multi-Run sandbox conversation history.

A sandbox conversation accumulates one Run per terminal+resume cycle (02_CORE § 5.3).
Each Run owns its own NDJSON log file in S3 (``TaskRun.log_url``). This module walks a
Task's Runs chronologically and concatenates each Run's stored ACP log entries into a
single chronological buffer — reusing the same S3/NDJSON read path that the per-run
``session_logs`` endpoint uses (``products/tasks/backend/api.py``), rather than reading
S3 ad hoc.

Pagination contract (single-shot, capped). The endpoint is not cursor-paginated: it
assembles the full cross-run buffer, then returns at most ``limit`` entries from one end
(``order``). ``has_more`` is ``True`` when the assembled buffer is longer than the slice
returned. ``after`` is an optional ISO8601 lower bound applied per entry before slicing —
the same timestamp filter the per-run path supports — giving callers a chronological
cursor for incremental "everything after T" reads. Cursor-style continuation across pages
is intentionally deferred (02_CORE § 4.6 perf note): the common case is 1-3 Runs well
under the 5000 cap, and a true cursor would have to thread an offset across N Run files.
"""

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog

from posthog.storage import object_storage

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

# Hard cap on entries returned in a single response, mirroring the per-run
# session_logs endpoint (products/tasks/backend/serializers.py::TaskRunSessionLogsQuerySerializer).
LOG_ENTRIES_MAX_LIMIT = 5000
LOG_ENTRIES_DEFAULT_LIMIT = 5000


class StoredLogEntry(dict[str, Any]):
    """A single ACP log entry as stored in the per-Run NDJSON file.

    Kept as a plain ``dict`` subtype for annotation clarity — the entries pass through
    verbatim (the cloud-agent owns the wire shape; 02_CORE § 4.1), so there is no
    schema to validate against here.
    """


class AssembledLog(dict[str, Any]):
    """The ``GET /log/`` response body: ``{ entries, has_more, current_run_status }``."""


def assemble_conversation_log(
    runs: "list[TaskRun]",
    *,
    after: datetime | None = None,
    limit: int = LOG_ENTRIES_DEFAULT_LIMIT,
    order: str = "asc",
) -> AssembledLog:
    """Concatenate every Run's stored log entries into one chronological buffer.

    Args:
        runs: The Task's Runs in chronological (``created_at`` asc) order. The caller owns
            ordering and team-scoping the query — this function only reads ``log_url`` and
            ``status`` off the rows it is handed.
        after: Optional ISO8601 lower bound; entries at or before it are dropped.
        limit: Max entries to return (capped at ``LOG_ENTRIES_MAX_LIMIT``).
        order: ``"asc"`` (chronological, default) or ``"desc"`` (newest first, for previews).

    Returns:
        ``{ "entries": StoredLogEntry[], "has_more": bool, "current_run_status": str | None }``.
        ``current_run_status`` is the last (most recent) Run's status, or ``None`` when the
        conversation has no Runs yet.
    """
    capped_limit = min(max(limit, 1), LOG_ENTRIES_MAX_LIMIT)

    entries: list[StoredLogEntry] = []
    for run in runs:
        entries.extend(_read_run_entries(run, after=after))

    if order == "desc":
        entries.reverse()

    page = entries[:capped_limit]
    has_more = len(entries) > len(page)

    current_run_status: str | None = runs[-1].status if runs else None

    return AssembledLog(
        entries=page,
        has_more=has_more,
        current_run_status=current_run_status,
    )


def _read_run_entries(run: "TaskRun", *, after: datetime | None) -> list[StoredLogEntry]:
    """Read and parse one Run's NDJSON log from S3, applying the optional ``after`` filter.

    Reuses the same S3/NDJSON read path as the per-run ``session_logs`` action: a single
    ``object_storage.read(run.log_url)`` followed by line-by-line ``json.loads``. Malformed
    lines are skipped (matching ``session_logs``), so a partially written log never 500s.
    """
    log_content = object_storage.read(run.log_url, missing_ok=True) or ""
    if not log_content.strip():
        return []

    parsed: list[StoredLogEntry] = []
    for line in log_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if after is not None and not _entry_after(entry, after):
            continue
        parsed.append(StoredLogEntry(entry))

    return parsed


def _entry_after(entry: dict[str, Any], after: datetime) -> bool:
    """Return whether ``entry`` is strictly after ``after``.

    Mirrors the per-run ``session_logs`` timestamp filter: entries without a parseable
    timestamp are dropped (treated as not-after), avoiding ``Z`` vs ``+00:00`` mismatches.
    """
    entry_ts = entry.get("timestamp", "")
    if not entry_ts or not isinstance(entry_ts, str):
        return False
    try:
        entry_dt = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return entry_dt > after
