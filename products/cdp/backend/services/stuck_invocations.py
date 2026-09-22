"""Recover CDP invocations whose lifecycle rows never reached a terminal status.

`hog_invocation_results` resolves a run's status with `argMax(status, version)`
over its lifecycle rows. An invocation whose terminal row was never produced
therefore reads `running` forever: the Runs tab shows it in flight, and the
rerun paginator's in-flight guard refuses to replay it. Nothing reconciles that
after the fact, because the cyclotron job the row described is already gone.

The only way to move such a run is to produce a terminal row carrying a higher
`version`, so this writes one to the same Kafka topic the CDP workers produce
to. Every other column is copied from the stored row, `invocation_globals`
included, because the rerun paginator rehydrates the replayed invocation from
that column.
"""

from dataclasses import field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from posthog.clickhouse.client.execute import sync_execute
from posthog.dataclasses import frozen
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_HOG_INVOCATION_RESULTS

# Stable, low-cardinality `error_kind` stamped on every row this writes, so the
# runs UI and the rerun filters can target exactly these recoveries and tell
# them apart from failures the destination itself produced.
STUCK_INVOCATION_ERROR_KIND = "stuck_invocation"

STUCK_INVOCATION_ERROR_MESSAGE = "This run never reported a result, so it was marked failed. Re-run it to try again."

# Matches the ClickHouse TTL on hog_invocation_results. Rows older than this are
# gone, so scanning further back only reads partitions that cannot match.
MAX_WINDOW_DAYS = 30

DELIVERY_TIMEOUT_SECONDS = 30.0

# Aliases are deliberately not named after their source columns: ClickHouse's
# analyzer resolves a name in WHERE to a same-named SELECT alias, which would
# turn `WHERE scheduled_at >= …` into an aggregate-in-WHERE error. Same reason
# the runs listing query aliases its aggregates `latest_*`.
#
# The age check sits in HAVING rather than WHERE because `scheduled_at` moves
# per lifecycle row (cyclotron rewrites it on every retry). Filtering rows by it
# could hide an invocation's terminal row while keeping its `running` one, which
# would report a finished run as stuck.
_STUCK_INVOCATIONS_QUERY = """
SELECT
    invocation_id,
    argMax(function_id, version) AS latest_function_id,
    argMax(parent_run_id, version) AS latest_parent_run_id,
    argMax(attempts, version) AS latest_attempts,
    argMax(is_retry, version) AS latest_is_retry,
    max(scheduled_at) AS latest_scheduled_at,
    argMax(first_scheduled_at, version) AS latest_first_scheduled_at,
    argMax(started_at, version) AS latest_started_at,
    argMax(event_uuid, version) AS latest_event_uuid,
    argMax(distinct_id, version) AS latest_distinct_id,
    argMax(person_id, version) AS latest_person_id,
    argMax(invocation_globals, version) AS latest_invocation_globals,
    max(version) AS latest_version
FROM hog_invocation_results
WHERE team_id = %(team_id)s
    AND function_kind = %(function_kind)s
    AND scheduled_at >= %(window_start)s
    {function_id_clause}
    {invocation_ids_clause}
GROUP BY invocation_id
HAVING argMax(status, version) = 'running'
    AND argMax(is_deleted, version) = 0
    AND max(scheduled_at) < %(cutoff)s
ORDER BY latest_scheduled_at ASC
LIMIT %(limit)s
"""


@frozen
class StuckInvocationScope:
    team_id: int
    function_kind: str
    # Both optional filters narrow the scan; omitting them covers every function
    # of this kind in the team.
    function_id: Optional[str]
    invocation_ids: tuple[str, ...]
    min_age: timedelta
    limit: int


@frozen
class StuckInvocation:
    invocation_id: str
    function_id: str
    parent_run_id: str
    attempts: int
    is_retry: int
    scheduled_at: datetime
    first_scheduled_at: datetime
    started_at: Optional[datetime]
    event_uuid: str
    distinct_id: str
    person_id: str
    # The triggering payload, still gzip+base64 encoded as the producer wrote
    # it. Kept out of `repr` so a customer payload cannot reach a traceback or a
    # log line just because this object was printed.
    invocation_globals: str = field(repr=False)
    version: int


def _iso_microseconds(value: datetime) -> str:
    # ClickHouse DateTime64(6) accepts 'YYYY-MM-DD HH:MM:SS.ffffff'. The Node
    # producer writes the same format onto this topic.
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _as_utc(value: datetime) -> datetime:
    # The ClickHouse driver returns naive datetimes for DateTime64 columns.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def find_stuck_invocations(scope: StuckInvocationScope, *, now: datetime) -> list[StuckInvocation]:
    params: dict[str, Any] = {
        "team_id": scope.team_id,
        "function_kind": scope.function_kind,
        "window_start": now - timedelta(days=MAX_WINDOW_DAYS),
        "cutoff": now - scope.min_age,
        "limit": scope.limit,
    }

    function_id_clause = ""
    if scope.function_id:
        function_id_clause = "AND function_id = %(function_id)s"
        params["function_id"] = scope.function_id

    invocation_ids_clause = ""
    if scope.invocation_ids:
        invocation_ids_clause = "AND invocation_id IN %(invocation_ids)s"
        params["invocation_ids"] = list(scope.invocation_ids)

    rows = sync_execute(
        _STUCK_INVOCATIONS_QUERY.format(
            function_id_clause=function_id_clause,
            invocation_ids_clause=invocation_ids_clause,
        ),
        params,
    )

    return [
        StuckInvocation(
            invocation_id=row[0],
            function_id=row[1],
            parent_run_id=row[2],
            attempts=row[3],
            is_retry=row[4],
            scheduled_at=_as_utc(row[5]),
            first_scheduled_at=_as_utc(row[6]),
            started_at=_as_utc(row[7]) if row[7] else None,
            event_uuid=row[8],
            distinct_id=row[9],
            person_id=row[10],
            invocation_globals=row[11],
            version=row[12],
        )
        for row in rows
    ]


def build_terminal_row(invocation: StuckInvocation, *, scope: StuckInvocationScope, now: datetime) -> dict[str, Any]:
    started_at = invocation.started_at
    duration_ms = max(0, int((now - started_at).total_seconds() * 1000)) if started_at else None

    # ReplacingMergeTree keeps the highest `version` per invocation, so a row
    # that does not beat the stored one is written and then silently ignored.
    # The producers stamp `version` from a wall clock in microseconds, which a
    # clock skew or a replayed row can push ahead of this process's clock.
    version = max(int(now.timestamp() * 1_000_000), invocation.version + 1)

    return {
        "team_id": scope.team_id,
        "function_kind": scope.function_kind,
        "function_id": invocation.function_id,
        "invocation_id": invocation.invocation_id,
        "parent_run_id": invocation.parent_run_id,
        "status": "failed",
        "attempts": invocation.attempts,
        "is_retry": invocation.is_retry,
        # Carried verbatim so the new row lands in the same daily partition as
        # the rows it collapses with, and keeps the run's original timing.
        "scheduled_at": _iso_microseconds(invocation.scheduled_at),
        "first_scheduled_at": _iso_microseconds(invocation.first_scheduled_at),
        "started_at": _iso_microseconds(started_at) if started_at else None,
        "finished_at": _iso_microseconds(now),
        "duration_ms": duration_ms,
        "error_kind": STUCK_INVOCATION_ERROR_KIND,
        "error_message": STUCK_INVOCATION_ERROR_MESSAGE,
        "event_uuid": invocation.event_uuid,
        "distinct_id": invocation.distinct_id,
        "person_id": invocation.person_id,
        "invocation_globals": invocation.invocation_globals,
        "version": str(version),
        "is_deleted": 0,
    }


def unstick_invocations(scope: StuckInvocationScope, *, now: datetime, dry_run: bool) -> list[StuckInvocation]:
    """Mark every stuck invocation in `scope` as failed, returning the ones matched.

    A dry run resolves the matches and writes nothing.
    """
    stuck = find_stuck_invocations(scope, now=now)
    if dry_run or not stuck:
        return stuck

    with producer_scope(topic=KAFKA_HOG_INVOCATION_RESULTS) as producer:
        deliveries = [
            producer.produce(
                topic=KAFKA_HOG_INVOCATION_RESULTS,
                data=build_terminal_row(invocation, scope=scope, now=now),
                # Same partitioning key the CDP producers use, so every row for
                # one invocation stays on one partition.
                key=invocation.invocation_id,
                log_key_on_delivery_failure=True,
            )
            for invocation in stuck
        ]

    for delivery in deliveries:
        delivery.get(timeout=DELIVERY_TIMEOUT_SECONDS)

    return stuck
