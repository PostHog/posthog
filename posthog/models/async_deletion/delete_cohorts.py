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
from dataclasses import replace
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db.models import BigIntegerField, Func, Max, QuerySet, TextField, Value
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

# How many queued rows one page of the marking pass holds. Bounds both the rows a single
# transaction rewrites and the memory the page occupies.
COHORT_MARK_PAGE_SIZE = 50_000

# Unfinished mutations on `cohortpeople` the sweep will tolerate before it stops enqueueing more.
# Mutations are enqueued asynchronously, so without this every target chunk lands at once and they
# all compete for the same background pool.
COHORT_MUTATION_CAPACITY = 2
COHORT_MUTATION_POLL_SECONDS = 30.0
# A mutation the sweep did not enqueue can hold the table indefinitely, so waiting for it needs its
# own bound; the sweep fails rather than blocking the run forever.
COHORT_MUTATION_TIMEOUT_SECONDS = 3600.0


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
class CohortKey:
    """The cohort a queued deletion names."""

    team_id: int
    cohort_id: int


@frozen
class MutationCounts:
    """How many `cohortpeople` mutations are in view, and how many of those are unfinished."""

    seen: int
    unfinished: int


@frozen
class CohortDeleteTarget:
    """One cohort's unit of work, collapsed from every deletion queued against it."""

    team_id: int
    cohort_id: int
    # The exclusive version bound, or None to remove every version. `Cohort_full` deletes the whole
    # cohort; `Cohort_stale` only removes what a later recalculation superseded.
    below_version: int | None

    @property
    def key(self) -> CohortKey:
        return CohortKey(team_id=self.team_id, cohort_id=self.cohort_id)

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


def _cohort_id(key: str) -> int | None:
    """The cohort id a queued deletion's key names, or None when it names nothing.

    Keys are written as `<cohort_id>_<version>` and, for a team that is not the cohort's own,
    `<cohort_id>_<version>_<team_id>` (see `posthog/api/cohort.py`). `version` is also the literal
    string "None" for a cohort that was never calculated, so the cohort id is the only part that is
    always a number.
    """
    head = key.split("_", 1)[0]
    return int(head) if head.isdigit() else None


def _queued(deletion_type: DeletionType) -> QuerySet[AsyncDeletion]:
    return AsyncDeletion.objects.filter(delete_verified_at__isnull=True, deletion_type=deletion_type)


def _collapse(deletion_type: DeletionType, limit: int = 0) -> list[CohortDeleteTarget]:
    """Reduce the queued deletions of one type to one target per cohort.

    The aggregation, the ordering and the cap all run in the database, so what comes back is bounded
    by `limit`, or by the number of distinct cohorts, rather than by the queue depth. A key that
    names no cohort is filtered out here and counted by the marking pass.
    """
    parseable = _queued(deletion_type).filter(key__regex=r"^\d+_")
    cohort_id = Cast(KeyPart("key", Value(r"^(\d+)_")), BigIntegerField())

    if deletion_type == DeletionType.Cohort_full:
        # Every version goes, so there is nothing to collapse beyond the cohort itself.
        cohorts = (
            parseable.annotate(cohort_id=cohort_id)
            .values_list("team_id", "cohort_id")
            .distinct()
            .order_by("team_id", "cohort_id")
        )
        return [
            CohortDeleteTarget(team_id=t, cohort_id=c, below_version=None)
            for t, c in (cohorts[:limit] if limit else cohorts)
        ]

    # Only versioned keys can bound a stale sweep; one without a numeric version names no bound.
    bounded = (
        parseable.filter(key__regex=r"^\d+_\d+")
        .annotate(
            cohort_id=cohort_id,
            version=Cast(KeyPart("key", Value(r"^\d+_(\d+)")), BigIntegerField()),
        )
        .values("team_id", "cohort_id")
        .annotate(below_version=Max("version"))
        .order_by("team_id", "cohort_id")
        .values_list("team_id", "cohort_id", "below_version")
    )
    return [
        CohortDeleteTarget(team_id=t, cohort_id=c, below_version=v)
        for t, c, v in (bounded[:limit] if limit else bounded)
    ]


def _server_now() -> datetime:
    [[now]] = sync_execute("SELECT now()")
    return now


def _mutation_counts(since: datetime | None = None) -> MutationCounts:
    """Mutations on `cohortpeople`, counting only ones created at or after `since`."""
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
    return MutationCounts(seen=seen, unfinished=unfinished)


def _wait_for_capacity(timeout: float = COHORT_MUTATION_TIMEOUT_SECONDS) -> None:
    """Block until `cohortpeople` is carrying fewer than `COHORT_MUTATION_CAPACITY` mutations.

    Bounded on purpose. A mutation this sweep did not enqueue can hold the table for as long as it
    likes, and the ClickHouse client is configured with no practical socket timeout, so an unbounded
    wait here is indistinguishable from a hang.
    """
    deadline = time.monotonic() + timeout
    while (unfinished := _mutation_counts().unfinished) >= COHORT_MUTATION_CAPACITY:
        if time.monotonic() > deadline:
            raise TimeoutError(f"cohortpeople still has {unfinished} unfinished mutation(s) after {timeout:.0f}s")
        logger.info("Waiting for cohortpeople mutation capacity", unfinished=unfinished)
        time.sleep(COHORT_MUTATION_POLL_SECONDS)


def _wait_for_drain(issued: int, since: datetime, timeout: float = COHORT_MUTATION_TIMEOUT_SECONDS) -> None:
    """Block until every mutation this sweep enqueued is visible and finished.

    Waiting on "nothing unfinished" alone is not enough. A mutation entry replicates through
    Keeper, so for a moment after the ALTER returns the queried host does not know it exists, and a
    drain that only counts unfinished work reads that gap as success and lets the person sweep
    start on top of a running mutation.
    """
    deadline = time.monotonic() + timeout
    while True:
        counts = _mutation_counts(since)
        if counts.seen >= issued and not counts.unfinished:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"cohortpeople has {counts.unfinished} unfinished mutation(s)"
                f" and {counts.seen} of {issued} visible after {timeout:.0f}s"
            )
        logger.info(
            "Waiting for cohortpeople mutations to drain",
            seen=counts.seen,
            issued=issued,
            unfinished=counts.unfinished,
        )
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


def _cleared(targets: list[CohortDeleteTarget]) -> set[CohortKey]:
    """The targets whose rows are already gone from `cohortpeople`.

    A deletion bounded at version V still has rows if and only if some row sits below V, which is
    true if and only if the cohort's lowest surviving version is below V. A cohort with no rows at
    all never appears in the lookup, so it clears whatever its bound.

    `sign` is deliberately not filtered. A membership the reader treats as removed (`sign = -1`)
    is still a row the sweep has to delete, and counting it here can only hold a cohort back for
    another run, never clear one whose rows are still present.
    """
    lowest: dict[CohortKey, int] = {}
    for chunk in chunked(targets, COHORT_DELETION_CHUNK_SIZE):
        conditions, params = _conditions([replace(target, below_version=None) for target in chunk])
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
            lowest[CohortKey(team_id=team_id, cohort_id=cohort_id)] = min_version

    return {
        target.key
        for target in targets
        if (surviving := lowest.get(target.key)) is None
        or (target.below_version is not None and surviving >= target.below_version)
    }


def _mark_verified(deletion_type: DeletionType, cleared: set[CohortKey]) -> int:
    """Tick off every queued deletion naming a cleared cohort. Returns how many rows were marked.

    Paged on the primary key rather than filtered on the cohort id. The cohort id lives inside
    `key`, and no index covers a prefix match on it under this database's collation, so a predicate
    shaped that way plans as a sequential scan and pays for the whole queue once per statement.
    Walking the primary key reads the queue once in total, and each update addresses rows by id.
    """
    if not cleared:
        return 0

    now = timezone.now()
    marked = 0
    unparseable = 0
    after = 0
    while True:
        page = list(
            _queued(deletion_type)
            .filter(pk__gt=after)
            .order_by("pk")
            .values_list("id", "team_id", "key")[:COHORT_MARK_PAGE_SIZE]
        )
        if not page:
            break
        after = page[-1][0]

        ids = []
        for row_id, team_id, key in page:
            cohort_id = _cohort_id(key)
            if cohort_id is None:
                unparseable += 1
            elif CohortKey(team_id=team_id, cohort_id=cohort_id) in cleared:
                ids.append(row_id)
        if ids:
            marked += AsyncDeletion.objects.filter(pk__in=ids).update(delete_verified_at=now)
        if len(page) < COHORT_MARK_PAGE_SIZE:
            break

    if unparseable:
        # Not fatal: a key the producer never wrote cannot match cohort rows either, so skipping it
        # loses no deletion. Counted because it means the key format has drifted.
        COHORT_DELETION_UNPARSEABLE_KEY_COUNTER.labels(deletion_type=deletion_type.name).inc(unparseable)
        logger.warning("Skipped cohort deletions with unparseable keys", count=unparseable, deletion_type=deletion_type)

    return marked


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
            cleared = _cleared(targets)
            marked = _mark_verified(deletion_type, cleared)
            logger.info("Marked cohort deletions verified", deletion_type=deletion_type.name, marked=marked)
            # Already gone, so sweeping them again would issue a mutation that removes nothing.
            targets = [target for target in targets if target.key not in cleared]
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
