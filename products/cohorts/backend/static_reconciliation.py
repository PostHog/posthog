"""Copy static cohort members that reached ClickHouse but not Postgres.

A population writes `person_static_cohort` first and Postgres second. When the second step reads nothing back, the
cohort finishes with an empty Postgres membership, so flags match nobody and the cohort shows a count of 0.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum

from django.core.cache import cache
from django.db.models import Q, QuerySet

import structlog
from prometheus_client import Counter

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE
from posthog.schema_enums import ProductKey

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import count_cohort_members, insert_cohort_people_into_pg

logger = structlog.get_logger(__name__)

RECONCILE_MAX_COHORTS_PER_RUN = 10
RECONCILE_PAGE_SIZE = 200
# A larger cohort holds the personhog insert path for too long in one task.
RECONCILE_MAX_MEMBERS = 1_000_000
# Persons deleted after the population stay in ClickHouse but cannot be copied, so a small gap never closes.
RECONCILE_MIN_MISSING_RATIO = 0.01
# A population still in progress, or one that only just finished, is left to its own task.
RECONCILE_SETTLE_DELAY = timedelta(hours=1)
RECONCILE_RECENT_WINDOW = timedelta(hours=48)
RECONCILE_RETRY_AFTER = timedelta(hours=48)
# A parked cohort is left alone until its ClickHouse count changes or this expires.
RECONCILE_PARK_FOR = timedelta(days=30)

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
    clickhouse_count: int


@frozen
class _Candidate:
    team_id: int
    cohort_id: int
    stored_count: int | None


def _attempt_cache_key(cohort_id: int) -> str:
    return f"static-cohort-reconcile:attempt:{cohort_id}"


def _park_cache_key(cohort_id: int) -> str:
    return f"static-cohort-reconcile:parked:{cohort_id}"


def _park(cohort_id: int, clickhouse_count: int) -> None:
    cache.set(_park_cache_key(cohort_id), clickhouse_count, timeout=int(RECONCILE_PARK_FOR.total_seconds()))


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
    return Cohort.objects.filter(is_static=True, deleted=False, is_calculating=False).filter(
        Q(last_calculation__lte=settled_before) | Q(last_calculation__isnull=True, created_at__lte=settled_before)
    )


def _candidates(queryset: QuerySet[Cohort]) -> list[_Candidate]:
    return [
        _Candidate(team_id=team_id, cohort_id=cohort_id, stored_count=count)
        for team_id, cohort_id, count in queryset.order_by("-id").values_list("team_id", "id", "count")[
            :RECONCILE_PAGE_SIZE
        ]
    ]


def _clickhouse_member_counts(candidates: list[_Candidate]) -> dict[int, int]:
    if not candidates:
        return {}
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    # nosemgrep: clickhouse-fstring-param-audit - table name from constant, values parameterized
    rows = sync_execute(
        f"SELECT cohort_id, uniqExact(person_id) FROM {PERSON_STATIC_COHORT_TABLE} WHERE team_id IN %(team_ids)s AND cohort_id IN %(cohort_ids)s GROUP BY cohort_id",
        {
            "team_ids": sorted({candidate.team_id for candidate in candidates}),
            "cohort_ids": sorted({candidate.cohort_id for candidate in candidates}),
        },
        workload=Workload.OFFLINE,  # background sweep, no person waits for it
        ch_user=ClickHouseUser.COHORTS,
    )
    return {int(cohort_id): int(member_count) for cohort_id, member_count in rows}


def _skipped_cohort_ids(candidates: list[_Candidate]) -> tuple[set[int], dict[int, int]]:
    attempt_keys = {_attempt_cache_key(candidate.cohort_id): candidate.cohort_id for candidate in candidates}
    park_keys = {_park_cache_key(candidate.cohort_id): candidate.cohort_id for candidate in candidates}
    attempted = {attempt_keys[key] for key in cache.get_many(list(attempt_keys))}
    parked = {park_keys[key]: count for key, count in cache.get_many(list(park_keys)).items()}
    return attempted, parked


def run_reconciliation_pass(*, now: datetime, dispatch: Callable[[StaticCohortToReconcile], None]) -> None:
    """Dispatch a repair for up to RECONCILE_MAX_COHORTS_PER_RUN static cohorts whose Postgres membership lags.

    Recently calculated cohorts go first. The rest of the budget walks every static cohort from newest to oldest
    with a cursor, one page per run, and starts again from the newest after the oldest.
    """
    settled = _settled_static_cohorts(now)
    recent = _candidates(settled.filter(last_calculation__gte=now - RECONCILE_RECENT_WINDOW))
    cursor = cache.get(RECONCILE_CURSOR_CACHE_KEY)
    backlog = _candidates(settled.filter(id__lt=cursor) if cursor is not None else settled)
    attempted, parked = _skipped_cohort_ids(recent + backlog)
    clickhouse_counts = _clickhouse_member_counts([c for c in recent + backlog if c.cohort_id not in attempted])
    recent_ids = {candidate.cohort_id for candidate in recent}
    dispatched = 0

    def consider(candidate: _Candidate) -> None:
        nonlocal dispatched
        if candidate.cohort_id in attempted:
            return
        clickhouse_count = clickhouse_counts.get(candidate.cohort_id, 0)
        if parked.get(candidate.cohort_id) == clickhouse_count:
            return
        decision = decide(stored_count=candidate.stored_count, clickhouse_count=clickhouse_count)
        if decision == ReconcileDecision.TOO_LARGE:
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
                dispatch(
                    StaticCohortToReconcile(
                        team_id=candidate.team_id, cohort_id=candidate.cohort_id, clickhouse_count=clickhouse_count
                    )
                )
            except Exception as error:
                STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="dispatch_failed").inc()
                capture_exception(
                    error, additional_properties={"cohort_id": candidate.cohort_id, "team_id": candidate.team_id}
                )
                return
            cache.set(_attempt_cache_key(candidate.cohort_id), True, timeout=int(RECONCILE_RETRY_AFTER.total_seconds()))
            dispatched += 1
            STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="dispatched").inc()

    for candidate in recent:
        if dispatched >= RECONCILE_MAX_COHORTS_PER_RUN:
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


def reconcile_static_cohort(cohort: StaticCohortToReconcile) -> None:
    """Copy the cohort's ClickHouse members to Postgres and store the new count.

    The repair holds `is_calculating` like a population does, so a CSV upload or a switch to dynamic cannot run
    under it. It writes nothing back if the cohort became dynamic or was deleted in the meantime.
    """
    owned = Cohort.objects.filter(team_id=cohort.team_id, id=cohort.cohort_id, is_static=True, deleted=False)
    if not owned.filter(is_calculating=False).update(is_calculating=True):
        STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="skipped_busy").inc()
        return
    released = False
    try:
        postgres_count = count_cohort_members(cohort.team_id, cohort.cohort_id, consistency="strong")
        if not _postgres_lags_clickhouse(postgres_count, cohort.clickhouse_count):
            owned.filter(is_calculating=True).update(is_calculating=False, count=postgres_count)
            released = True
            STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="already_complete").inc()
            return
        row = owned.get()
        # min_rows makes the copy wait for a replica that holds every row instead of storing a partial copy.
        insert_cohort_people_into_pg(row, team_id=cohort.team_id, min_rows=cohort.clickhouse_count)
        owned.filter(is_calculating=True).update(is_calculating=False, count=row.count)
        released = True
        if row.count == postgres_count:
            _park(cohort.cohort_id, cohort.clickhouse_count)
            STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="parked").inc()
        else:
            STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="reconciled").inc()
        logger.info(
            "static_cohort_reconciled",
            team_id=cohort.team_id,
            cohort_id=cohort.cohort_id,
            postgres_count=postgres_count,
            reconciled_count=row.count,
            clickhouse_count=cohort.clickhouse_count,
        )
    finally:
        if not released:
            owned.filter(is_calculating=True).update(is_calculating=False)
