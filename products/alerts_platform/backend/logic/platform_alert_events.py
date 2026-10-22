"""Writes the shared platform's check history to ClickHouse.

One row per check. The table is append-only and TTL'd, so a check that confirmed the alert is
recorded alongside the ones that moved it, and nothing has to decide which checks are worth
keeping.

ClickHouse has no unique constraint, so the insert carries a deduplication token instead. The
token names the batch by its contents, and the replicated engine drops a second insert that
arrives under a token it has already seen. A reader still deduplicates on
`(configuration_id, alert_id, evaluation_key)`, because the token only covers a retry of the same
batch and the engine only remembers a bounded window of them.
"""

import json
import hashlib
from collections.abc import Collection, Sequence
from dataclasses import field, fields
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    PlatformAlertHistory,
    PlatformCheckEntry,
    PlatformCheckEvent,
    PlatformCheckEventPage,
    PlatformCheckPage,
    PlatformLastCheck,
    PlatformStateChange,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TABLE

logger = structlog.get_logger(__name__)


@frozen
class PlatformAlertEventRow:
    """One check, as the history table stores it.

    The three snapshots make the row self-sufficient: a threshold edited between a check and a
    retried send cannot change what the message claims was breached, and a rename cannot make one
    thread contradict itself.
    """

    team_id: int
    # The source whose check this was, so a reader can tell sources apart without a Postgres join.
    source_kind: str
    configuration_id: UUID
    alert_id: UUID
    grouping_key: str
    evaluation_key: str
    kind: str
    alert_name: str
    previous_state: str
    state: str
    # The firing this check concerned, which on a resolve is the one it ended. The alert row
    # holds the firing it is in now, so the two differ on exactly that check.
    episode_started_at: datetime | None
    value: float | None
    labels: dict[str, str]
    condition_snapshot: dict[str, Any]
    source_config_snapshot: dict[str, Any]
    query_duration_ms: int | None
    error_message: str | None
    consecutive_failures: int
    muted_notification: str
    occurred_at: datetime
    source_detail: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        """The row as ClickHouse takes it, derived from the fields so a new one cannot be missed.

        Only the four the wire needs in another shape are named.
        """
        return {f.name: getattr(self, f.name) for f in fields(self)} | {
            "condition_snapshot": json.dumps(self.condition_snapshot),
            "source_config_snapshot": json.dumps(self.source_config_snapshot),
            "error_message": self.error_message or "",
            "source_detail": json.dumps(self.source_detail) if self.source_detail else "",
        }


# Derived from the row rather than listed again, so a new column cannot reach the dataclass and
# miss the insert.
_COLUMNS = tuple(f.name for f in fields(PlatformAlertEventRow))
_INSERT_SQL = f"INSERT INTO {PLATFORM_ALERT_EVENTS_TABLE} ({', '.join(_COLUMNS)}) VALUES"


def _deduplication_token(team_id: int, rows: Sequence[PlatformAlertEventRow]) -> str:
    """Names a batch by the evaluations in it, so a retry of that batch carries the same name.

    The activity is retried by Temporal, and a retry that follows a committed transaction can
    reach an insert the first attempt had already landed. `insert_deduplication_token` makes the
    replicated engine drop the second one.

    Built from the batch's contents rather than from `(team_id, cutoff)`, because two sources can
    record for one team at one cutoff and a token those two shared would silently drop the second
    source's rows.

    The grouping key is in the digest because one configuration writes one row per group once a
    source groups its results. Without it, two batches that hold the same configurations and
    evaluation keys but different groups take the same name, and the engine drops the second one
    whole.
    """
    digest = hashlib.sha256(str(team_id).encode())
    for configuration_id, grouping_key, evaluation_key in sorted(
        (str(row.configuration_id), row.grouping_key, row.evaluation_key) for row in rows
    ):
        digest.update(b"\0")
        digest.update(configuration_id.encode())
        digest.update(b"\0")
        digest.update(grouping_key.encode())
        digest.update(b"\0")
        digest.update(evaluation_key.encode())
    return digest.hexdigest()


def _execute(query: str, args: Any, *, team_id: int, settings: dict[str, Any] | None = None) -> Any:
    """`sync_execute` as the platform's own user, so this bookkeeping never takes from `default`'s
    per-user concurrency budget. A pod without that user wired falls back to its own default user."""
    return sync_execute(query, args, team_id=team_id, settings=settings, ch_user=ClickHouseUser.ALERTS_PLATFORM)


def insert_events(team_id: int, rows: Sequence[PlatformAlertEventRow]) -> int:
    """Records a batch's history. Returns how many rows it wrote.

    Never raises. History is a record of what the platform decided, not a step in deciding it, so
    a ClickHouse outage must not fail a batch whose state and schedule are already written. The
    cost of a failure is a gap a comparison sees, which is what the counter here is for.
    """
    if not rows:
        return 0
    try:
        # `sync_execute` requires both tags. The platform product rather than a source's, because
        # the table serves every source and the write is the platform's own bookkeeping.
        tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
        _execute(
            _INSERT_SQL,
            [row.as_row() for row in rows],
            settings={"insert_deduplication_token": _deduplication_token(team_id, rows)},
            team_id=team_id,
        )
    except Exception as error:
        logger.exception(
            "Failed to record platform alert check history",
            team_id=team_id,
            rows=len(rows),
            error=str(error),
        )
        return 0
    return len(rows)


_ANNOUNCED_ROWS = f"""
FROM {PLATFORM_ALERT_EVENTS_TABLE}
WHERE team_id = %(team_id)s
  AND configuration_id = %(configuration_id)s
  AND evaluation_key = %(evaluation_key)s
  AND (kind != %(check_kind)s OR has(%(incident_grouping_keys)s, grouping_key))
ORDER BY grouping_key, occurred_at DESC
LIMIT 1 BY grouping_key
"""

_ANNOUNCEMENT_COLUMNS = """grouping_key, kind, episode_started_at, value, labels, condition_snapshot,
       source_config_snapshot, error_message, occurred_at, source_detail, alert_name, consecutive_failures"""

_ANNOUNCEMENT_SQL = f"SELECT {_ANNOUNCEMENT_COLUMNS} {_ANNOUNCED_ROWS}"

# Deals the announced groups out by their position in key order, so the parts of one evaluation
# cover every group exactly once, and each part decodes only its own rows.
_ANNOUNCEMENT_PART_SQL = f"""
SELECT {_ANNOUNCEMENT_COLUMNS}
FROM (
    SELECT *, row_number() OVER (ORDER BY grouping_key) - 1 AS position
    FROM ({_ANNOUNCEMENT_SQL})
)
WHERE modulo(position, %(parts)s) = %(part)s
ORDER BY grouping_key
"""

_ANNOUNCED_KINDS_SQL = f"SELECT grouping_key, kind {_ANNOUNCED_ROWS}"


def announcement(
    team_id: int,
    configuration_id: str,
    evaluation_key: str,
    *,
    source: SourceKind,
    incident_grouping_keys: Collection[str] = (),
    part: int = 0,
    parts: int = 1,
) -> EvaluationAnnouncement | None:
    """What one evaluation left for a destination to say, or None when it announced nothing.

    Rows whose kind is `CHECK` are excluded here rather than in the caller. They are recorded so
    a comparison can read every check, and they say nothing, so a message built from one would
    have no headline. The exception is a group in `incident_grouping_keys`: cooldown or mute held
    its announcement, but its firing still opened or closed, and a paging destination needs that row.

    `LIMIT 1 BY grouping_key` is the read's own deduplication. The insert carries a token the
    engine drops a repeat under, but it only remembers a bounded window of them, so a retry far
    enough behind writes a second row for a group. The newest is the one this evaluation meant.

    With `parts` above one, only the groups of that `part` come back, and None when it has none.
    """
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    parameters: dict[str, Any] = {
        "team_id": team_id,
        "configuration_id": configuration_id,
        "evaluation_key": evaluation_key,
        "check_kind": AlertEventKind.CHECK.value,
        "incident_grouping_keys": list(incident_grouping_keys),
    }
    if parts > 1:
        rows = _execute(_ANNOUNCEMENT_PART_SQL, {**parameters, "part": part, "parts": parts}, team_id=team_id)
    else:
        rows = _execute(_ANNOUNCEMENT_SQL, parameters, team_id=team_id)
    if not rows:
        return None

    transitions = tuple(
        AnnouncedTransition(
            grouping_key=grouping_key,
            kind=AlertEventKind(kind),
            episode_started_at=episode_started_at,
            value=value,
            labels=dict(labels or {}),
            condition=_snapshot(condition_snapshot),
            source_config=_snapshot(source_config_snapshot),
            error_message=error_message or None,
            occurred_at=occurred_at,
            evaluation_key=evaluation_key,
            source_detail=_snapshot(source_detail),
        )
        for grouping_key, kind, episode_started_at, value, labels, condition_snapshot, source_config_snapshot, error_message, occurred_at, source_detail, _, _ in rows
    )
    # Evaluation-level, and the same on every row of one evaluation, so the first row carries it.
    *_, alert_name, consecutive_failures = rows[0]
    return EvaluationAnnouncement(
        configuration_id=configuration_id,
        source=source,
        alert_name=alert_name,
        consecutive_failures=consecutive_failures,
        transitions=transitions,
    )


def announced_kinds(
    team_id: int,
    configuration_id: str,
    evaluation_key: str,
    *,
    incident_grouping_keys: Collection[str] = (),
) -> dict[str, AlertEventKind]:
    """The kind of every group `announcement` returns across all parts, without the rows' payloads."""
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    rows = _execute(
        _ANNOUNCED_KINDS_SQL,
        {
            "team_id": team_id,
            "configuration_id": configuration_id,
            "evaluation_key": evaluation_key,
            "check_kind": AlertEventKind.CHECK.value,
            "incident_grouping_keys": list(incident_grouping_keys),
        },
        team_id=team_id,
    )
    return {grouping_key: AlertEventKind(kind) for grouping_key, kind in rows}


def _snapshot(raw: str) -> dict[str, Any]:
    """A snapshot column the writer may have left empty, or that predates the field it holds."""
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


# The inner read deduplicates on the pair the writer names, as `announcement` does. The outer one
# keeps the checks that moved the alert and the newest check, so a page of alerts that check every
# minute returns a few rows each rather than a day of them.
_HISTORY_SQL = f"""
SELECT configuration_id, occurred_at, previous_state, state, error_message, is_latest
FROM (
    SELECT configuration_id, occurred_at, previous_state, state, error_message,
           occurred_at = max(occurred_at) OVER (PARTITION BY configuration_id) AS is_latest
    FROM (
        SELECT configuration_id, alert_id, evaluation_key, occurred_at, previous_state, state, error_message
        FROM {PLATFORM_ALERT_EVENTS_TABLE}
        WHERE team_id = %(team_id)s
          AND configuration_id IN %(configuration_ids)s
          AND grouping_key = ''
          AND occurred_at >= %(since)s
          AND occurred_at < %(until)s
        ORDER BY configuration_id, alert_id, occurred_at, evaluation_key
        LIMIT 1 BY alert_id, evaluation_key
    )
)
WHERE previous_state != state OR is_latest
ORDER BY configuration_id, occurred_at
"""


def history(
    team_id: int, configuration_ids: Collection[UUID], *, since: datetime, until: datetime
) -> dict[UUID, PlatformAlertHistory]:
    """Each configuration's state changes and last check in `[since, until)`, in one query.

    Only the ungrouped instance is read, because a source that shows one state per alert has no
    groups. A configuration with no check in the window is left out.

    Raises on a ClickHouse failure, because only the caller knows what it can show instead.
    """
    if not configuration_ids:
        return {}
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    # Not `_execute`: the web API calls this too, and naming a user would replace the one
    # `sync_execute` picks for request traffic.
    rows = sync_execute(
        _HISTORY_SQL,
        {"team_id": team_id, "configuration_ids": list(configuration_ids), "since": since, "until": until},
        team_id=team_id,
    )
    changes: dict[UUID, list[PlatformStateChange]] = {}
    latest: dict[UUID, tuple[datetime, str]] = {}
    for configuration_id, occurred_at, previous_state, state, error_message, is_latest in rows:
        if previous_state != state:
            changes.setdefault(configuration_id, []).append(
                PlatformStateChange(
                    occurred_at=occurred_at,
                    previous_state=PlatformAlertState(previous_state),
                    state=PlatformAlertState(state),
                )
            )
        if is_latest:
            latest[configuration_id] = (occurred_at, error_message)
    return {
        configuration_id: PlatformAlertHistory(
            state_changes=tuple(changes.get(configuration_id, ())),
            last_checked_at=last_checked_at,
            last_error_message=error_message or None,
        )
        for configuration_id, (last_checked_at, error_message) in latest.items()
    }


# A source reads these to fill in a page it can show without them, so a stalled query gives up
# rather than holding the request.
_READ_BUDGET: Final = {"max_execution_time": 5}


def _microseconds(moment: datetime) -> str:
    # A datetime parameter is sent to the second, which would move a window's end past checks inside it.
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


# Deduplicated as `_HISTORY_SQL` is. The quiet checks are dropped before the deduplication, which
# is safe because two copies of one check are identical rows. The total is a window over every
# matching check, so one query answers both the page and the count a paginated list needs.
_NOTABLE_CHECKS_SQL = f"""
SELECT occurred_at, evaluation_key, previous_state, state, value, condition_snapshot, query_duration_ms,
       error_message, count() OVER () AS total
FROM (
    SELECT alert_id, evaluation_key, occurred_at, previous_state, state, value, condition_snapshot,
           query_duration_ms, error_message
    FROM {PLATFORM_ALERT_EVENTS_TABLE}
    WHERE team_id = %(team_id)s
      AND configuration_id = %(configuration_id)s
      AND grouping_key = ''
      AND occurred_at >= %(since)s
      AND (previous_state != state OR error_message != '')
    ORDER BY alert_id, occurred_at, evaluation_key
    LIMIT 1 BY alert_id, evaluation_key
)
ORDER BY occurred_at DESC, evaluation_key DESC
LIMIT %(limit)s
"""


def notable_checks(team_id: int, configuration_id: UUID, *, since: datetime, limit: int) -> PlatformCheckEventPage:
    """The newest `limit` checks since `since` that moved the configuration's state or failed.

    A check that confirmed the state it found is left out, because a source that lists events
    shows what changed. Only the ungrouped instance is read, as in `history`.

    Raises on a ClickHouse failure, because only the caller knows what it can show instead.
    """
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    rows = sync_execute(
        _NOTABLE_CHECKS_SQL,
        {"team_id": team_id, "configuration_id": configuration_id, "since": since, "limit": limit},
        team_id=team_id,
    )
    return PlatformCheckEventPage(
        events=tuple(
            PlatformCheckEvent(
                occurred_at=occurred_at,
                evaluation_key=evaluation_key,
                previous_state=PlatformAlertState(previous_state),
                state=PlatformAlertState(state),
                value=value,
                condition=_snapshot(condition_snapshot),
                query_duration_ms=query_duration_ms,
                error_message=error_message or None,
            )
            for occurred_at, evaluation_key, previous_state, state, value, condition_snapshot, query_duration_ms, error_message, _ in rows
        ),
        total=rows[0][-1] if rows else 0,
    )


_CHECKS_SQL = f"""
SELECT occurred_at, evaluation_key, state, value, error_message, count() OVER () AS total
FROM (
    SELECT alert_id, evaluation_key, occurred_at, state, value, error_message
    FROM {PLATFORM_ALERT_EVENTS_TABLE}
    WHERE team_id = %(team_id)s
      AND configuration_id = %(configuration_id)s
      AND grouping_key = ''
      AND occurred_at >= toDateTime64(%(since)s, 6, 'UTC')
      AND occurred_at < toDateTime64(%(until)s, 6, 'UTC')
    ORDER BY alert_id, occurred_at, evaluation_key
    LIMIT 1 BY alert_id, evaluation_key
)
ORDER BY occurred_at DESC, evaluation_key DESC
LIMIT %(limit)s OFFSET %(offset)s
"""

_CHECK_COUNT_SQL = f"""
SELECT count()
FROM (
    SELECT alert_id, evaluation_key
    FROM {PLATFORM_ALERT_EVENTS_TABLE}
    WHERE team_id = %(team_id)s
      AND configuration_id = %(configuration_id)s
      AND grouping_key = ''
      AND occurred_at >= toDateTime64(%(since)s, 6, 'UTC')
      AND occurred_at < toDateTime64(%(until)s, 6, 'UTC')
    LIMIT 1 BY alert_id, evaluation_key
)
"""


def check_page(
    team_id: int, configuration_id: UUID, *, since: datetime, until: datetime, limit: int, offset: int
) -> PlatformCheckPage:
    """One configuration's checks in `[since, until)`, newest first, with how many the window holds.

    Only the ungrouped instance is read, for the same reason as `history`. Raises on a ClickHouse
    failure, because only the caller knows what it can show instead.
    """
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    # Not `_execute`, for the same reason as `history`.
    parameters = {
        "team_id": team_id,
        "configuration_id": configuration_id,
        "since": _microseconds(since),
        "until": _microseconds(until),
        "limit": limit,
        "offset": offset,
    }
    rows = sync_execute(_CHECKS_SQL, parameters, team_id=team_id, settings=_READ_BUDGET)
    if rows:
        total = rows[0][5]
    elif offset:
        # A page past the end has no row to carry the window's count, so it is counted on its own.
        total = sync_execute(_CHECK_COUNT_SQL, parameters, team_id=team_id, settings=_READ_BUDGET)[0][0]
    else:
        total = 0
    return PlatformCheckPage(
        total=total,
        checks=tuple(
            PlatformCheckEntry(
                occurred_at=occurred_at,
                evaluation_key=evaluation_key,
                state=PlatformAlertState(state),
                value=value,
                error_message=error_message or None,
            )
            for occurred_at, evaluation_key, state, value, error_message, _ in rows
        ),
    )


# Deduplication does not matter here, because two copies of one check are identical rows. The tuple
# keeps a NULL value, which `argMax` would otherwise skip in favor of an older check's.
_LAST_CHECKS_SQL = f"""
SELECT configuration_id, max(occurred_at), argMax(tuple(value), (occurred_at, evaluation_key)).1
FROM {PLATFORM_ALERT_EVENTS_TABLE}
WHERE team_id = %(team_id)s
  AND configuration_id IN %(configuration_ids)s
  AND grouping_key = ''
GROUP BY configuration_id
"""


def last_checks(team_id: int, configuration_ids: Collection[UUID]) -> dict[UUID, PlatformLastCheck]:
    """Each configuration's newest check across its whole history, in one query.

    Only the ungrouped instance is read, as in `history`. A configuration with no check is left out.
    Raises on a ClickHouse failure, because only the caller knows what it can show instead.
    """
    if not configuration_ids:
        return {}
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    # Not `_execute`, for the same reason as `history`.
    rows = sync_execute(
        _LAST_CHECKS_SQL,
        {"team_id": team_id, "configuration_ids": list(configuration_ids)},
        team_id=team_id,
        settings=_READ_BUDGET,
    )
    return {
        configuration_id: PlatformLastCheck(checked_at=checked_at, value=value)
        for configuration_id, checked_at, value in rows
    }
