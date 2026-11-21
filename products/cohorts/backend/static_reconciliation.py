"""Copy static cohort members that reached ClickHouse but not Postgres.

A population writes `person_static_cohort` first and Postgres second. When the second step reads nothing back, the
cohort finishes with an empty Postgres membership, so flags match nobody and the cohort shows a count of 0.

The sweep drains the cohorts that broke this way and then keeps running as a safety net for any later gap.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast

from django.core.cache import cache
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import Counter
from redis import Redis
from redis.client import Pipeline

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
    insert_cohort_members,
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

# Longer than a ClickHouse delete of a removed member takes to apply, and than RECONCILE_RETRY_AFTER, so a repair
# whose final cleanup failed still finds the mark the next time it runs.
RECONCILE_REMOVAL_TTL = timedelta(days=7)

# Removals and additions are user actions, so a slow Redis must not hold them up for the default timeout.
_USER_PATH_REDIS_TIMEOUT_SECONDS = 1.0

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


def _user_path_redis() -> Redis:
    return get_client(
        socket_timeout=_USER_PATH_REDIS_TIMEOUT_SECONDS, socket_connect_timeout=_USER_PATH_REDIS_TIMEOUT_SECONDS
    )


def _removed_members_key(cohort_id: int) -> str:
    return f"static-cohort-reconcile:removed:{cohort_id}"


@contextmanager
def _logging_redis_errors(cohort_id: int) -> Iterator[None]:
    # A lost mark only reopens a rare race, so a Redis error must not fail the removal, addition or population.
    try:
        yield
    except SoftTimeLimitExceeded:
        raise
    except Exception as err:
        capture_exception(err, additional_properties={"cohort_id": cohort_id})


def _removed_at(mark: bytes) -> int:
    return int(mark.split(b":", 1)[0])


def _delete_marks_older_than(client: Redis, key: str, removed_before: dict[str, float]) -> None:
    """Delete each mark recorded before its time, in one transaction so a removal recorded meanwhile survives."""
    person_uuids = list(removed_before)

    def delete(pipeline: Pipeline) -> None:
        # A watched pipeline runs commands before multi() right away, so this is the reply, not the pipeline.
        marks = cast(list[bytes | None], pipeline.hmget(key, person_uuids))
        older = [
            person_uuid
            for person_uuid, mark in zip(person_uuids, marks)
            if mark is not None and _removed_at(mark) < removed_before[person_uuid]
        ]
        pipeline.multi()
        if older:
            pipeline.hdel(key, *older)

    if person_uuids:
        client.transaction(delete, key)


def record_static_cohort_member_removal(*, cohort_id: int, person_id: int, person_uuid: str) -> None:
    """Keep a removed member out of repairs while ClickHouse deletes it asynchronously.

    Call it before the Postgres delete, so a repair that copies the member back afterwards removes it again.
    """
    with _logging_redis_errors(cohort_id):
        key = _removed_members_key(cohort_id)
        pipeline = _user_path_redis().pipeline(transaction=False)
        # Keyed by UUID, which is all a population's copy knows. The value lets each mark age out on its own.
        pipeline.hset(key, person_uuid, f"{int(time.time())}:{person_id}")
        pipeline.expire(key, int(RECONCILE_REMOVAL_TTL.total_seconds()))
        pipeline.execute()


def clear_static_cohort_member_removals(*, cohort_id: int, person_uuids: list[str]) -> None:
    """Forget the removal of members that were explicitly added again, so a repair does not delete them.

    Call it before the Postgres insert, which `_delete_recently_removed_members` relies on.
    """
    with _logging_redis_errors(cohort_id):
        if person_uuids:
            _user_path_redis().hdel(_removed_members_key(cohort_id), *person_uuids)


def clear_static_cohort_member_removals_written_after(*, cohort_id: int, written_at: dict[str, int]) -> None:
    """Forget the removal of members whose ClickHouse row a population wrote after the removal.

    A row written before it may be the removed member's, still there until its ClickHouse delete applies.
    """
    with _logging_redis_errors(cohort_id):
        _delete_marks_older_than(_user_path_redis(), _removed_members_key(cohort_id), dict(written_at))


def _delete_recently_removed_members(row: Cohort) -> None:
    """Delete from Postgres every member removed within RECONCILE_REMOVAL_TTL and not added again since."""
    client = get_client()
    key = _removed_members_key(row.pk)
    expired_before = time.time() - RECONCILE_REMOVAL_TTL.total_seconds()
    removed: dict[str, int] = {}
    expired: dict[str, float] = {}
    for field, mark in client.hgetall(key).items():
        person_uuid = field.decode()
        if _removed_at(mark) < expired_before:
            expired[person_uuid] = expired_before
        else:
            removed[person_uuid] = int(mark.split(b":", 1)[1])
    _delete_marks_older_than(client, key, expired)
    for person_uuid, person_id in removed.items():
        deleted = delete_cohort_member(row.team_id, row.pk, person_id)
        # An addition clears the mark before its insert, so a mark gone now means an addition since the snapshot
        # above, which this delete may have undone.
        if deleted and not client.hexists(key, person_uuid):
            insert_cohort_members(row.team_id, row.pk, [person_id], row.version, _skip_ownership_check=True)


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
        for team_id, cohort_id, count in rows[:limit]
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
    _delete_recently_removed_members(row)
    # Count again instead of reusing the selection's count. A member removed since then would leave `min_rows` above
    # what ClickHouse holds, so the copy would repeat after every read-back wait and then fail.
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
    try:
        insert_cohort_people_into_pg(row, team_id=cohort.team_id, min_rows=members.people)
    finally:
        # A member removed during the copy may still be in ClickHouse, so the copy can bring it back, also when it
        # fails partway.
        _delete_recently_removed_members(row)
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
