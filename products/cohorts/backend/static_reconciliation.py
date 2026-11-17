"""Copy static cohort members that reached ClickHouse but not Postgres.

A population writes `person_static_cohort` first and Postgres second. When the second step reads nothing back, the
cohort finishes with an empty Postgres membership, so flags match nobody and the cohort shows a count of 0.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum

from django.core.cache import cache
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
from prometheus_client import Counter

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE
from posthog.redis import get_client
from posthog.schema_enums import ProductKey

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import (
    count_cohort_members,
    delete_cohort_member,
    insert_cohort_people_into_pg,
)

logger = structlog.get_logger(__name__)

RECONCILE_MAX_COHORTS_PER_RUN = 10
# The rest of the budget stays with the backlog, so a burst of recent cohorts cannot stop the cursor.
RECONCILE_MAX_RECENT_PER_RUN = 5
RECONCILE_PAGE_SIZE = 200
# No known failure above this. It keeps one repair to about 100 personhog pages, so the extra write load stays
# predictable while the backlog drains. Larger cohorts are logged for a person to decide.
RECONCILE_MAX_MEMBERS = 1_000_000
# Persons deleted after the population stay in ClickHouse but cannot be copied, so a small gap never closes.
RECONCILE_MIN_MISSING_RATIO = 0.01
# A population still in progress, or one that only just finished, is left to its own task.
RECONCILE_SETTLE_DELAY = timedelta(hours=1)
RECONCILE_RECENT_WINDOW = timedelta(hours=48)
RECONCILE_RETRY_AFTER = timedelta(hours=48)
RECONCILE_RECHECK_IN_SYNC_AFTER = timedelta(hours=6)
# A parked cohort is left alone until its ClickHouse count changes or this expires.
RECONCILE_PARK_FOR = timedelta(days=30)

# Longer than a ClickHouse delete of a removed member takes to apply.
RECONCILE_REMOVAL_TTL = timedelta(hours=24)

RECONCILE_CURSOR_CACHE_KEY = "static-cohort-reconcile:cursor"
RECONCILE_CURSOR_TTL = timedelta(days=30)

STATIC_COHORT_RECONCILE_COUNTER = Counter(
    "cohort_static_reconcile_total",
    "Static cohorts whose Postgres membership lags ClickHouse, by what the reconciliation did with them.",
    labelnames=["outcome"],
)


class ReconcileDecision(StrEnum):
    IN_SYNC = "in_sync"
    RECONCILE = "reconcile"
    TOO_LARGE = "too_large"


@frozen
class StaticCohortToReconcile:
    team_id: int
    cohort_id: int


@frozen
class _Candidate:
    team_id: int
    cohort_id: int
    stored_count: int | None


def _hold_cache_key(cohort_id: int) -> str:
    """A cohort with this key is not counted or dispatched again until the key expires."""
    return f"static-cohort-reconcile:hold:{cohort_id}"


def _hold(cohort_id: int, duration: timedelta) -> None:
    cache.set(_hold_cache_key(cohort_id), True, timeout=int(duration.total_seconds()))


def _removed_members_key(cohort_id: int) -> str:
    return f"static-cohort-reconcile:removed:{cohort_id}"


# Same clock and format as the `_timestamp` that static cohort inserts write, so ClickHouse compares them directly.
_REMOVED_AT_FORMAT = "%Y-%m-%d %H:%M:%S"


def record_static_cohort_member_removal(*, cohort_id: int, person_id: int, person_uuid: str) -> None:
    """Keep a removed member out of repairs while ClickHouse deletes it asynchronously.

    Call it before the Postgres delete, so a repair that copies the member back afterwards removes it again.
    """
    key = _removed_members_key(cohort_id)
    pipeline = get_client().pipeline(transaction=False)
    pipeline.hset(key, f"{person_id}:{person_uuid}", datetime.now().strftime(_REMOVED_AT_FORMAT))
    pipeline.expire(key, int(RECONCILE_REMOVAL_TTL.total_seconds()))
    pipeline.execute()


def _delete_recently_removed_members(cohort: StaticCohortToReconcile) -> None:
    """Delete members removed within RECONCILE_REMOVAL_TTL from Postgres, unless they were added again since."""
    client = get_client()
    key = _removed_members_key(cohort.cohort_id)
    expired_before = (datetime.now() - RECONCILE_REMOVAL_TTL).strftime(_REMOVED_AT_FORMAT)
    removed: dict[str, tuple[int, str]] = {}
    expired: list[bytes] = []
    for field, removed_at_raw in client.hgetall(key).items():
        removed_at = removed_at_raw.decode()
        if removed_at < expired_before:
            expired.append(field)
            continue
        person_id, person_uuid = field.decode().split(":", 1)
        removed[person_uuid] = (int(person_id), removed_at)
    if expired:
        client.hdel(key, *expired)
    if not removed:
        return

    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    # nosemgrep: clickhouse-fstring-param-audit - table name from constant, values parameterized
    rows = sync_execute(
        f"SELECT toString(person_id), formatDateTime(max(_timestamp), '%%Y-%%m-%%d %%H:%%i:%%S') FROM {PERSON_STATIC_COHORT_TABLE} WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND person_id IN %(person_uuids)s GROUP BY person_id",
        {"team_id": cohort.team_id, "cohort_id": cohort.cohort_id, "person_uuids": list(removed)},
        workload=Workload.OFFLINE,  # background repair, no person waits for it
        ch_user=ClickHouseUser.COHORTS,
    )
    last_written: dict[str, str] = dict(rows)
    for person_uuid, (person_id, removed_at) in removed.items():
        # A row written at or after the removal means the person was added again, which this must not undo.
        if last_written.get(person_uuid, "") >= removed_at:
            continue
        delete_cohort_member(cohort.team_id, cohort.cohort_id, person_id)


def _park_cache_key(cohort_id: int) -> str:
    return f"static-cohort-reconcile:parked:{cohort_id}"


def _park(cohort_id: int, clickhouse_rows: int) -> None:
    cache.set(_park_cache_key(cohort_id), clickhouse_rows, timeout=int(RECONCILE_PARK_FOR.total_seconds()))


def _postgres_lags_clickhouse(postgres_count: int | None, clickhouse_count: int) -> bool:
    missing = clickhouse_count - (postgres_count or 0)
    return missing > 0 and (not postgres_count or missing > clickhouse_count * RECONCILE_MIN_MISSING_RATIO)


def decide(*, stored_count: int | None, clickhouse_count: int) -> ReconcileDecision:
    if not _postgres_lags_clickhouse(stored_count, clickhouse_count):
        return ReconcileDecision.IN_SYNC
    if clickhouse_count > RECONCILE_MAX_MEMBERS:
        return ReconcileDecision.TOO_LARGE
    return ReconcileDecision.RECONCILE


def _settled_static_cohorts(now: datetime) -> QuerySet[Cohort]:
    settled_before = now - RECONCILE_SETTLE_DELAY
    return (
        # A failed population leaves a partial set in ClickHouse, and copying it would make flags match that set.
        Cohort.objects.filter(is_static=True, deleted=False, is_calculating=False, errors_calculating=0)
        .filter(
            Q(last_calculation__lte=settled_before) | Q(last_calculation__isnull=True, created_at__lte=settled_before)
        )
        # reset_stuck_cohorts stamps last_error_at when it dispatches a population, which sets is_calculating only
        # once its task starts.
        .filter(Q(last_error_at__isnull=True) | Q(last_error_at__lte=settled_before))
    )


def _candidates(queryset: QuerySet[Cohort], *, limit: int | None) -> list[_Candidate]:
    rows = queryset.order_by("-id").values_list("team_id", "id", "count")
    return [
        _Candidate(team_id=team_id, cohort_id=cohort_id, stored_count=count)
        for team_id, cohort_id, count in (rows[:limit] if limit is not None else rows)
    ]


@frozen
class _ClickHouseMembers:
    rows: int
    people: int


def _clickhouse_row_counts(candidates: list[_Candidate]) -> dict[int, int]:
    """Count rows, not distinct people: count() keeps no per-member state, and it is never below the distinct count,
    so the size cap stays safe on a page of very large cohorts."""
    if not candidates:
        return {}
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    # nosemgrep: clickhouse-fstring-param-audit - table name from constant, values parameterized
    rows = sync_execute(
        f"SELECT cohort_id, count() FROM {PERSON_STATIC_COHORT_TABLE} WHERE team_id IN %(team_ids)s AND cohort_id IN %(cohort_ids)s GROUP BY cohort_id",
        {
            "team_ids": sorted({candidate.team_id for candidate in candidates}),
            "cohort_ids": sorted({candidate.cohort_id for candidate in candidates}),
        },
        workload=Workload.OFFLINE,  # background sweep, no person waits for it
        ch_user=ClickHouseUser.COHORTS,
    )
    return {int(cohort_id): int(row_count) for cohort_id, row_count in rows}


def _clickhouse_members(cohort: StaticCohortToReconcile) -> _ClickHouseMembers:
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    # nosemgrep: clickhouse-fstring-param-audit - table name from constant, values parameterized
    [(row_count, people)] = sync_execute(
        f"SELECT count(), uniqExact(person_id) FROM {PERSON_STATIC_COHORT_TABLE} WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s",
        {"team_id": cohort.team_id, "cohort_id": cohort.cohort_id},
        workload=Workload.OFFLINE,  # background repair, no person waits for it
        ch_user=ClickHouseUser.COHORTS,
    )
    return _ClickHouseMembers(rows=int(row_count), people=int(people))


def _skipped_cohort_ids(candidates: list[_Candidate]) -> tuple[set[int], dict[int, int]]:
    hold_keys = {_hold_cache_key(candidate.cohort_id): candidate.cohort_id for candidate in candidates}
    park_keys = {_park_cache_key(candidate.cohort_id): candidate.cohort_id for candidate in candidates}
    held = {hold_keys[key] for key in cache.get_many(list(hold_keys))}
    parked = {park_keys[key]: count for key, count in cache.get_many(list(park_keys)).items()}
    return held, parked


def run_reconciliation_pass(*, now: datetime, dispatch: Callable[[StaticCohortToReconcile], None]) -> None:
    """Dispatch a repair for up to RECONCILE_MAX_COHORTS_PER_RUN static cohorts whose Postgres membership lags.

    Recently calculated cohorts go first. The rest of the budget walks every static cohort from newest to oldest
    with a cursor, one page per run, and starts again from the newest after the oldest.
    """
    settled = _settled_static_cohorts(now)
    # The whole window, so held cohorts cannot fill the page and hide an older recent one.
    recent_window = _candidates(settled.filter(last_calculation__gte=now - RECONCILE_RECENT_WINDOW), limit=None)
    cursor = cache.get(RECONCILE_CURSOR_CACHE_KEY)
    backlog = _candidates(settled.filter(id__lt=cursor) if cursor is not None else settled, limit=RECONCILE_PAGE_SIZE)
    held, parked = _skipped_cohort_ids(recent_window + backlog)
    recent = [candidate for candidate in recent_window if candidate.cohort_id not in held][:RECONCILE_PAGE_SIZE]
    clickhouse_counts = _clickhouse_row_counts([c for c in recent + backlog if c.cohort_id not in held])
    recent_ids = {candidate.cohort_id for candidate in recent}
    dispatched = 0

    def consider(candidate: _Candidate) -> None:
        nonlocal dispatched
        if candidate.cohort_id in held:
            return
        clickhouse_count = clickhouse_counts.get(candidate.cohort_id, 0)
        if parked.get(candidate.cohort_id) == clickhouse_count:
            return
        decision = decide(stored_count=candidate.stored_count, clickhouse_count=clickhouse_count)
        if decision == ReconcileDecision.IN_SYNC and candidate.cohort_id in recent_ids:
            _hold(candidate.cohort_id, RECONCILE_RECHECK_IN_SYNC_AFTER)
        elif decision == ReconcileDecision.TOO_LARGE:
            _park(candidate.cohort_id, clickhouse_count)
            STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="skipped_too_large").inc()
            logger.warning(
                "static_cohort_reconcile_skipped_too_large",
                team_id=candidate.team_id,
                cohort_id=candidate.cohort_id,
                clickhouse_count=clickhouse_count,
                stored_count=candidate.stored_count,
            )
        elif decision == ReconcileDecision.RECONCILE:
            try:
                dispatch(StaticCohortToReconcile(team_id=candidate.team_id, cohort_id=candidate.cohort_id))
            except Exception as error:
                STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="dispatch_failed").inc()
                capture_exception(
                    error, additional_properties={"cohort_id": candidate.cohort_id, "team_id": candidate.team_id}
                )
                return
            _hold(candidate.cohort_id, RECONCILE_RETRY_AFTER)
            dispatched += 1
            STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="dispatched").inc()

    for candidate in recent:
        if dispatched >= RECONCILE_MAX_RECENT_PER_RUN:
            break
        consider(candidate)

    next_cursor = cursor
    for candidate in backlog:
        if dispatched >= RECONCILE_MAX_COHORTS_PER_RUN:
            break
        if candidate.cohort_id not in recent_ids:
            consider(candidate)
        next_cursor = candidate.cohort_id
    else:
        if len(backlog) < RECONCILE_PAGE_SIZE:
            next_cursor = None

    if next_cursor is None:
        cache.delete(RECONCILE_CURSOR_CACHE_KEY)
    else:
        cache.set(RECONCILE_CURSOR_CACHE_KEY, next_cursor, timeout=int(RECONCILE_CURSOR_TTL.total_seconds()))


def _write_count(row: Cohort, count: int) -> None:
    # A population or CSV import that has set `is_calculating`, or that finished or failed since `row` was read,
    # writes its own count.
    Cohort.objects.filter(
        team_id=row.team_id,
        id=row.pk,
        is_static=True,
        deleted=False,
        is_calculating=False,
        errors_calculating=0,
        last_calculation=row.last_calculation,
        last_error_at=row.last_error_at,
    ).update(count=count)


def reconcile_static_cohort(cohort: StaticCohortToReconcile) -> None:
    """Copy the cohort's ClickHouse members to Postgres and store the new count.

    The repair does not set `is_calculating`: the stuck-cohort sweep reads that flag on a cohort calculated more
    than an hour ago as a dead population. The copy skips existing members, so a population running at the same
    time is safe.
    """
    row = _settled_static_cohorts(timezone.now()).filter(team_id=cohort.team_id, id=cohort.cohort_id).first()
    if row is None:
        cache.delete(_hold_cache_key(cohort.cohort_id))
        STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="skipped_busy").inc()
        return
    # A retry after a failed cleanup would otherwise find the cohort complete and return before cleaning up.
    _delete_recently_removed_members(cohort)
    # Rows deleted since the selection would make its count unreachable, and every read-back wait would copy again.
    members = _clickhouse_members(cohort)
    postgres_count = count_cohort_members(cohort.team_id, cohort.cohort_id, consistency="strong")
    decision = decide(stored_count=postgres_count, clickhouse_count=members.people)
    if decision == ReconcileDecision.IN_SYNC:
        _write_count(row, postgres_count)
        # Duplicate ClickHouse rows keep the selection's row count above the people, so it would pick the cohort again.
        _park(cohort.cohort_id, members.rows)
        STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="already_complete").inc()
        return
    if decision == ReconcileDecision.TOO_LARGE:
        STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="skipped_too_large").inc()
        return

    # min_rows makes the copy wait for a replica that holds every row instead of storing a partial copy.
    insert_cohort_people_into_pg(row, team_id=cohort.team_id, min_rows=members.people)
    # A member removed during the copy may still be in ClickHouse, so the copy can bring it back.
    _delete_recently_removed_members(cohort)
    # Recount here: the copy logs a failed recount and keeps the old count, which would park a repaired cohort.
    reconciled_count = count_cohort_members(cohort.team_id, cohort.cohort_id, consistency="strong")
    _write_count(row, reconciled_count)
    if reconciled_count == postgres_count:
        # The selection compares a parked cohort by its row count, so that is what the park records.
        _park(cohort.cohort_id, members.rows)
        STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="parked").inc()
    else:
        STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="reconciled").inc()
    logger.info(
        "static_cohort_reconciled",
        team_id=cohort.team_id,
        cohort_id=cohort.cohort_id,
        postgres_count=postgres_count,
        reconciled_count=reconciled_count,
        clickhouse_count=members.people,
    )
