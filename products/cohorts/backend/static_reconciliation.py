"""Copy static cohort members that reached ClickHouse but not Postgres.

A population writes `person_static_cohort` first and Postgres second. When the second step reads nothing back, the
cohort finishes with an empty Postgres membership, so flags match nobody and the cohort shows a count of 0.
"""

from datetime import datetime, timedelta

from django.core.cache import cache
from django.db.models import Q, QuerySet

import structlog
from prometheus_client import Counter

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE
from posthog.schema_enums import ProductKey

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import insert_cohort_people_into_pg

logger = structlog.get_logger(__name__)

RECONCILE_MAX_COHORTS_PER_RUN = 10
RECONCILE_PAGE_SIZE = 200
# A larger cohort holds the personhog insert path for too long in one task. Such cohorts are logged and skipped.
RECONCILE_MAX_MEMBERS = 1_000_000
# Persons deleted after the population stay in ClickHouse but cannot be copied, so a small gap never closes.
RECONCILE_MIN_MISSING_RATIO = 0.01
# A population still in progress, or one that only just finished, is left to its own task.
RECONCILE_SETTLE_DELAY = timedelta(hours=1)
RECONCILE_RECENT_WINDOW = timedelta(hours=48)
# A gap that one repair cannot close would otherwise take the budget of every run.
RECONCILE_RETRY_AFTER = timedelta(hours=48)

RECONCILE_CURSOR_CACHE_KEY = "static-cohort-reconcile:cursor"
# The cursor walks a full pass of every static cohort once in several days. The bound only keeps a stale key away.
RECONCILE_CURSOR_TTL_SECONDS = 30 * 24 * 60 * 60

STATIC_COHORT_RECONCILE_COUNTER = Counter(
    "cohort_static_reconcile_total",
    "Static cohorts whose Postgres membership lags ClickHouse, by what the reconciliation did with them.",
    labelnames=["outcome"],
)


@frozen
class StaticCohortToReconcile:
    team_id: int
    cohort_id: int


@frozen
class _Candidate:
    team_id: int
    cohort_id: int
    stored_count: int | None


def _attempt_cache_key(cohort_id: int) -> str:
    return f"static-cohort-reconcile:attempt:{cohort_id}"


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
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.COHORTS,
    )
    return {int(cohort_id): int(member_count) for cohort_id, member_count in rows}


def _postgres_lags_clickhouse(stored_count: int | None, clickhouse_count: int) -> bool:
    missing = clickhouse_count - (stored_count or 0)
    return missing > 0 and (not stored_count or missing > clickhouse_count * RECONCILE_MIN_MISSING_RATIO)


def select_static_cohorts_to_reconcile(*, now: datetime) -> list[StaticCohortToReconcile]:
    """Pick up to RECONCILE_MAX_COHORTS_PER_RUN static cohorts whose Postgres membership lags ClickHouse.

    Recently calculated cohorts go first. The rest of the budget walks every static cohort from newest to oldest
    with a cursor, one page per run, and starts again from the newest after the oldest.
    """
    settled = _settled_static_cohorts(now)
    recent = _candidates(settled.filter(last_calculation__gte=now - RECONCILE_RECENT_WINDOW))
    cursor = cache.get(RECONCILE_CURSOR_CACHE_KEY)
    backlog = _candidates(settled.filter(id__lt=cursor) if cursor is not None else settled)
    clickhouse_counts = _clickhouse_member_counts(recent + backlog)

    selected: list[StaticCohortToReconcile] = []
    selected_ids: set[int] = set()

    def select_if_lagging(candidate: _Candidate) -> None:
        clickhouse_count = clickhouse_counts.get(candidate.cohort_id, 0)
        if candidate.cohort_id in selected_ids or not _postgres_lags_clickhouse(
            candidate.stored_count, clickhouse_count
        ):
            return
        if not cache.add(
            _attempt_cache_key(candidate.cohort_id), True, timeout=int(RECONCILE_RETRY_AFTER.total_seconds())
        ):
            return
        if clickhouse_count > RECONCILE_MAX_MEMBERS:
            STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="skipped_too_large").inc()
            logger.warning(
                "static_cohort_reconcile_skipped_too_large",
                team_id=candidate.team_id,
                cohort_id=candidate.cohort_id,
                clickhouse_count=clickhouse_count,
                stored_count=candidate.stored_count,
            )
            return
        selected.append(StaticCohortToReconcile(team_id=candidate.team_id, cohort_id=candidate.cohort_id))
        selected_ids.add(candidate.cohort_id)
        STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="selected").inc()

    for candidate in recent:
        if len(selected) >= RECONCILE_MAX_COHORTS_PER_RUN:
            break
        select_if_lagging(candidate)

    next_cursor = cursor
    for candidate in backlog:
        if len(selected) >= RECONCILE_MAX_COHORTS_PER_RUN:
            break
        select_if_lagging(candidate)
        next_cursor = candidate.cohort_id
    else:
        if len(backlog) < RECONCILE_PAGE_SIZE:
            next_cursor = None

    if next_cursor is None:
        cache.delete(RECONCILE_CURSOR_CACHE_KEY)
    else:
        cache.set(RECONCILE_CURSOR_CACHE_KEY, next_cursor, timeout=RECONCILE_CURSOR_TTL_SECONDS)
    return selected


def reconcile_static_cohort(*, team_id: int, cohort_id: int) -> None:
    """Copy the cohort's ClickHouse members to Postgres and store the new count."""
    cohort = Cohort.objects.filter(
        team_id=team_id, id=cohort_id, is_static=True, deleted=False, is_calculating=False
    ).first()
    if cohort is None:
        return
    stored_count = cohort.count
    insert_cohort_people_into_pg(cohort, team_id=team_id)
    Cohort.objects.filter(team_id=team_id, id=cohort_id, is_static=True).update(count=cohort.count)
    STATIC_COHORT_RECONCILE_COUNTER.labels(outcome="reconciled").inc()
    logger.info(
        "static_cohort_reconciled",
        team_id=team_id,
        cohort_id=cohort_id,
        stored_count=stored_count,
        reconciled_count=cohort.count,
    )
