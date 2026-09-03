"""Sweep `cohortpeople` rows for cohorts that were deleted, or recalculated past a version.

A queued deletion is bookkeeping, not a unit of work. `posthog/api/cohort.py` writes one
`AsyncDeletion` per team that can see a cohort, so one deleted cohort can queue thousands of rows
that all name the same `(team_id, cohort_id)`. Working from the rows directly means holding every
one of them in memory and issuing a table-sized mutation per 500 of them, neither of which is
bounded by anything the cohort data itself controls.

So the sweep collapses the queue into targets first. Every queued deletion for one
`(team_id, cohort_id)` becomes a single target, because the ORed predicates it would otherwise
produce reduce to one:

    (version < V1) OR (version < V2) OR ... == version < max(Vi)

The collapse is exact rather than approximate, and it is what bounds the sweep: memory and
mutation count follow the number of distinct cohorts, which the queue cannot inflate.
"""

import time
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db.models import BigIntegerField, Func, Max, Q, QuerySet, TextField, Value
from django.db.models.functions import Cast
from django.utils import timezone

import structlog
from more_itertools import chunked
from prometheus_client import Counter

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.models.async_deletion import AsyncDeletion, DeletionType

logger = structlog.get_logger(__name__)

COHORT_DELETION_MARK_FAILURE_COUNTER = Counter(
    "posthog_cohort_deletion_mark_failure_total",
    "Times cohort deletion mark failed",
)

COHORT_DELETION_RUN_FAILURE_COUNTER = Counter(
    "posthog_cohort_deletion_run_failure_total",
    "Times cohort deletion run failed",
)

COHORT_DELETION_UNPARSEABLE_KEY_COUNTER = Counter(
    "posthog_cohort_deletion_unparseable_keys_total",
    "Queued cohort deletions whose key does not name a cohort, and so were skipped",
    ["deletion_type"],
)

# How many targets one mutation's predicate ORs together. Each target contributes an indexed
# `(team_id, cohort_id)` range, so this bounds predicate size, not the rows a mutation reads.
COHORT_DELETION_CHUNK_SIZE = 500

# How many targets one `delete_verified_at` UPDATE covers. Targets carry very different row
# counts, so this is deliberately far smaller than the mutation chunk: it bounds how many rows a
# single transaction rewrites, not how much SQL it takes to say so.
COHORT_VERIFY_UPDATE_CHUNK_SIZE = 50

# Unfinished mutations on `cohortpeople` the sweep will tolerate before it stops enqueueing more.
# Mutations are enqueued asynchronously, so without this every target chunk lands at once and they
# all compete for the same background pool.
COHORT_MUTATION_CAPACITY = 2
COHORT_MUTATION_POLL_SECONDS = 30.0
# A mutation the sweep did not enqueue can hold the table indefinitely, so waiting for capacity
# needs its own bound; the pass fails rather than blocking the run forever.
COHORT_MUTATION_CAPACITY_TIMEOUT_SECONDS = 3600.0


# nosemgrep: python.django.security.audit.extends-custom-expression.extends-custom-expression
class KeyPart(Func):
    """Postgres `substring(text from pattern)`, returning the first capture group or NULL.

    The pattern is always a literal from this module and the only expression is a column, so no
    caller-supplied text reaches the SQL. Capturing rather than splitting is what makes the cast
    downstream safe: a key whose version part is the literal "None" yields NULL instead of a value
    `bigint` cannot parse, so no plan that plays the cast before the filter can fail the query.
    """

    function = "substring"
    arity = 2
    template = "%(function)s(%(expressions)s)"
    arg_joiner = " from "
    output_field = TextField()


@frozen
class CohortDeleteTarget:
    """One `(team_id, cohort_id)` unit of work, collapsed from every deletion queued against it."""

    team_id: int
    cohort_id: int
    # The exclusive version bound, or None to remove every version. `Cohort_full` deletes the whole
    # cohort; `Cohort_stale` only removes what a later recalculation superseded.
    below_version: int | None

    @property
    def condition(self) -> tuple[str, dict[str, Any]]:
        """The ClickHouse predicate for this target, with its parameters."""
        suffix = f"{self.team_id}_{self.cohort_id}"
        params: dict[str, Any] = {f"team_id_{suffix}": self.team_id, f"cohort_id_{suffix}": self.cohort_id}
        clause = f"( team_id = %(team_id_{suffix})s AND cohort_id = %(cohort_id_{suffix})s"
        if self.below_version is not None:
            params[f"version_{suffix}"] = self.below_version
            clause += f" AND version < %(version_{suffix})s"
        return clause + " )", params


def _conditions(targets: list[CohortDeleteTarget]) -> tuple[list[str], dict[str, Any]]:
    clauses, params = [], {}
    for target in targets:
        clause, target_params = target.condition
        clauses.append(clause)
        params.update(target_params)
    return clauses, params


def _queued(deletion_type: DeletionType) -> QuerySet[AsyncDeletion]:
    return AsyncDeletion.objects.filter(delete_verified_at__isnull=True, deletion_type=deletion_type)


def _collapse(deletion_type: DeletionType, limit: int = 0) -> list[CohortDeleteTarget]:
    """Reduce the queued deletions of one type to one target per cohort.

    The aggregation runs in the database, so what comes back is bounded by the number of distinct
    cohorts rather than by the queue depth.

    Keys are written as `<cohort_id>_<version>` and, for a team that is not the cohort's own,
    `<cohort_id>_<version>_<team_id>` (see `posthog/api/cohort.py`). `version` is also the literal
    string "None" for a cohort that was never calculated. So the cohort id is the only part that is
    always a number, and a key that does not start with one names nothing this sweep can act on.
    """
    queued = _queued(deletion_type)
    parseable = queued.filter(key__regex=r"^\d+_")
    if skipped := queued.exclude(key__regex=r"^\d+_").count():
        # Not fatal: a key the producer never wrote cannot match cohort rows either, so skipping it
        # loses no deletion. Counted because it means the key format has drifted.
        COHORT_DELETION_UNPARSEABLE_KEY_COUNTER.labels(deletion_type=deletion_type.name).inc(skipped)
        logger.warning("Skipping cohort deletions with unparseable keys", count=skipped, deletion_type=deletion_type)

    cohort_id = Cast(KeyPart("key", Value(r"^(\d+)_")), BigIntegerField())

    targets: list[CohortDeleteTarget]
    if deletion_type == DeletionType.Cohort_full:
        # Every version goes, so there is nothing to collapse beyond the cohort itself.
        cohorts = parseable.annotate(cohort_id=cohort_id).values_list("team_id", "cohort_id").distinct().order_by()
        targets = [CohortDeleteTarget(team_id=t, cohort_id=c, below_version=None) for t, c in cohorts]
    else:
        # Only versioned keys can bound a stale sweep; one without a numeric version names no bound.
        bounded = (
            parseable.filter(key__regex=r"^\d+_\d+")
            .annotate(
                cohort_id=cohort_id,
                version=Cast(KeyPart("key", Value(r"^\d+_(\d+)")), BigIntegerField()),
            )
            .values("team_id", "cohort_id")
            .annotate(below_version=Max("version"))
            .order_by()
            .values_list("team_id", "cohort_id", "below_version")
        )
        targets = [CohortDeleteTarget(team_id=t, cohort_id=c, below_version=v) for t, c, v in bounded]

    targets.sort(key=lambda target: (target.team_id, target.cohort_id))
    # A cap leaves the rest queued, so the next run picks them up.
    return targets[:limit] if limit else targets


def _server_now() -> datetime:
    [[now]] = sync_execute("SELECT now()")
    return now


def _mutation_counts(since: datetime | None = None) -> tuple[int, int]:
    """(seen, unfinished) mutations on `cohortpeople`, counting only ones created at or after `since`."""
    window = "AND create_time >= %(since)s" if since else ""
    # nosemgrep: clickhouse-fstring-param-audit - window is a literal chosen here, not caller input
    [[seen, unfinished]] = sync_execute(
        f"""
        SELECT count(), countIf(NOT is_done)
        FROM system.mutations
        WHERE database = %(database)s AND table = 'cohortpeople' AND NOT is_killed {window}
        """,
        {"database": settings.CLICKHOUSE_DATABASE, "since": since},
    )
    return seen, unfinished


def _wait_for_capacity(timeout: float = COHORT_MUTATION_CAPACITY_TIMEOUT_SECONDS) -> None:
    """Block until `cohortpeople` is carrying fewer than `COHORT_MUTATION_CAPACITY` mutations.

    Bounded on purpose. A mutation this sweep did not enqueue can hold the table for as long as it
    likes, and the ClickHouse client is configured with no practical socket timeout, so an unbounded
    wait here is indistinguishable from a hang.
    """
    deadline = time.monotonic() + timeout
    while (unfinished := _mutation_counts()[1]) >= COHORT_MUTATION_CAPACITY:
        if time.monotonic() > deadline:
            raise TimeoutError(f"cohortpeople still has {unfinished} unfinished mutation(s) after {timeout:.0f}s")
        logger.info("Waiting for cohortpeople mutation capacity", unfinished=unfinished)
        time.sleep(COHORT_MUTATION_POLL_SECONDS)


def _wait_for_drain(issued: int, since: datetime, timeout: float = COHORT_MUTATION_CAPACITY_TIMEOUT_SECONDS) -> None:
    """Block until every mutation this sweep enqueued is visible and finished.

    Waiting on "nothing unfinished" alone is not enough. A mutation entry replicates through
    Keeper, so for a moment after the ALTER returns the queried host does not know it exists, and a
    drain that only counts unfinished work reads that gap as success and lets the person sweep
    start on top of a running mutation.
    """
    deadline = time.monotonic() + timeout
    while True:
        seen, unfinished = _mutation_counts(since)
        if seen >= issued and not unfinished:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"cohortpeople has {unfinished} unfinished mutation(s) and {seen} of {issued} visible"
                f" after {timeout:.0f}s"
            )
        logger.info("Waiting for cohortpeople mutations to drain", seen=seen, issued=issued, unfinished=unfinished)
        time.sleep(COHORT_MUTATION_POLL_SECONDS)


def _delete(targets: list[CohortDeleteTarget]) -> int:
    """Remove the cohort rows each target names, one mutation per chunk. Returns mutations issued.

    `lightweight_deletes_sync` is set here rather than left to the server, which defaults it to
    "wait for every replica". That default would block each chunk inside the client for as long as
    the mutation takes, with no bound and no progress reporting. Enqueueing asynchronously and
    pacing on `system.mutations` instead keeps the concurrency explicit and every wait bounded.
    """
    issued = 0
    for chunk in chunked(targets, COHORT_DELETION_CHUNK_SIZE):
        _wait_for_capacity()
        conditions, params = _conditions(list(chunk))
        # nosemgrep: clickhouse-fstring-param-audit - conditions come from CohortDeleteTarget.condition
        sync_execute(
            f"""
            DELETE FROM cohortpeople
            WHERE {" OR ".join(conditions)}
            """,
            params,
            settings={"lightweight_deletes_sync": 0},
        )
        issued += 1
    return issued


def _lowest_versions(targets: list[CohortDeleteTarget]) -> dict[tuple[int, int], int]:
    """The lowest version still present in `cohortpeople` for each target that has any rows.

    This is what decides verification exactly. A queued deletion bounded at version V has rows left
    if and only if some row sits below V, which is true if and only if the cohort's lowest surviving
    version is below V. A cohort missing from the result has no rows at all, so every deletion
    queued against it is done whatever its bound.
    """
    lowest: dict[tuple[int, int], int] = {}
    for chunk in chunked(targets, COHORT_DELETION_CHUNK_SIZE):
        pairs = list(chunk)
        conditions, params = _conditions(
            [CohortDeleteTarget(team_id=t.team_id, cohort_id=t.cohort_id, below_version=None) for t in pairs]
        )
        # nosemgrep: clickhouse-fstring-param-audit - conditions come from CohortDeleteTarget.condition
        rows = sync_execute(
            f"""
            SELECT team_id, cohort_id, min(version)
            FROM cohortpeople
            WHERE {" OR ".join(conditions)}
            GROUP BY team_id, cohort_id
            """,
            params,
            settings={},
        )
        for team_id, cohort_id, min_version in rows:
            lowest[(team_id, cohort_id)] = min_version
    return lowest


def _mark_verified(
    deletion_type: DeletionType, targets: list[CohortDeleteTarget]
) -> tuple[int, set[CohortDeleteTarget]]:
    """Tick off the queued deletions whose rows are gone. Returns the row count and the targets cleared.

    Filtering by `deletion_type` and a `<cohort_id>_` key prefix rides the unique index on
    (deletion_type, key), so a cohort's rows are found without scanning the queue.
    """
    lowest = _lowest_versions(targets)
    now = timezone.now()
    marked = 0
    cleared_targets: set[CohortDeleteTarget] = set()

    for chunk in chunked(targets, COHORT_VERIFY_UPDATE_CHUNK_SIZE):
        predicate = Q(pk__in=[])
        batch: list[CohortDeleteTarget] = []
        for target in chunk:
            surviving = lowest.get((target.team_id, target.cohort_id))
            if surviving is not None and (target.below_version is None or surviving < target.below_version):
                # Rows this target still has to remove; nothing queued against it is done.
                continue
            predicate |= Q(team_id=target.team_id, key__startswith=f"{target.cohort_id}_")
            batch.append(target)
        if not batch:
            continue
        marked += _queued(deletion_type).filter(predicate).update(delete_verified_at=now)
        cleared_targets.update(batch)

    return marked, cleared_targets


def sweep_cohort_deletions(max_cohorts: int = 0) -> list[str]:
    """Tick off cohorts whose rows are already gone, then remove the rows still queued.

    `max_cohorts` caps how many cohorts one run takes on, per deletion type, 0 for all of them.
    Whatever it excludes stays queued for the next run.

    Marking runs first, and reports on what earlier runs removed. Mutations are enqueued
    asynchronously, so the rows this run deletes are still readable when it finishes; a marking pass
    placed after the delete would find them and tick off nothing, every run, forever.

    Each pass is guarded on its own: failing to tick off cohorts whose rows are already gone must
    not stop the pass that removes rows.
    """
    failed = []
    issued = 0
    started_at = _server_now()

    for deletion_type in (DeletionType.Cohort_full, DeletionType.Cohort_stale):
        targets = _collapse(deletion_type, limit=max_cohorts)
        if not targets:
            logger.info("No cohort deletions queued", deletion_type=deletion_type.name)
            continue

        try:
            marked, cleared = _mark_verified(deletion_type, targets)
            logger.info("Marked cohort deletions verified", deletion_type=deletion_type.name, marked=marked)
            # Already gone, so sweeping them again would issue a mutation that removes nothing.
            targets = [target for target in targets if target not in cleared]
        except Exception:
            logger.exception("Failed to mark cohort deletions done", deletion_type=deletion_type.name)
            COHORT_DELETION_MARK_FAILURE_COUNTER.inc()
            failed.append(f"mark:{deletion_type.name}")

        if not targets:
            continue
        try:
            logger.warning("Sweeping cohortpeople", deletion_type=deletion_type.name, cohorts=len(targets))
            mutations = _delete(targets)
            issued += mutations
            logger.info("Issued cohort delete mutations", deletion_type=deletion_type.name, mutations=mutations)
        except Exception:
            logger.exception("Failed to run cohort deletions", deletion_type=deletion_type.name)
            COHORT_DELETION_RUN_FAILURE_COUNTER.inc()
            failed.append(f"run:{deletion_type.name}")

    # Raised, never recorded as a failed pass. The caller chains the person sweep on this returning,
    # and the two must not mutate at the same time, so an undrained table has to stop the run rather
    # than hand back a result that reads as "finished with a warning".
    _wait_for_drain(issued, started_at)
    return failed
