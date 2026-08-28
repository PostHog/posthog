from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q, QuerySet, Value
from django.db.models.functions import Greatest

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade import api as data_modeling_facade
from products.warehouse_sources.backend.facade import api as warehouse_facade

from ...facade.enums import SubjectType, SuiteRunStatus
from ...models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from ..contracts import CleanupOutcome

LOGGER = get_logger(__name__)

COMPILED_QUERY_RETENTION_DAYS = 30
CHECK_RUN_RETENTION_DAYS = 90
SUITE_RUN_RETENTION_DAYS = 90
STALE_SUITE_HOURS = 24
STALE_SUITE_ERROR = "The workflow stopped without recording a result."
RETENTION_DELETE_BATCH_SIZE = 1_000
# A row created while the sweep is running postdates the snapshot of live subjects its team's pass
# took, so it would read as pointing at a subject that does not exist. Spared this round instead.
SUBJECT_GRACE_HOURS = 1

_COUNTER_COLUMNS = {
    "passed": "checks_passed",
    "failed": "checks_failed",
    "errored": "checks_errored",
    "skipped": "checks_skipped",
}


def _heartbeat() -> None:
    # Called from the sweep itself so a long pass keeps reporting progress; a direct call outside a
    # worker (a test, a shell) has no activity to report to.
    if activity.in_activity():
        activity.heartbeat()


def _delete_in_batches(queryset: "QuerySet[Any]") -> dict[str, int]:
    """Delete a queryset in id-batches, returning how many rows went per model label.

    One unbounded ``.delete()`` loads every matched row and everything that cascades with it into
    Django's collector. Each suite drags its check runs in, so capping the parent rows per pass
    bounds that memory whatever the reverse relations pull along.
    """
    model = queryset.model
    totals: dict[str, int] = defaultdict(int)
    while ids := list(queryset.values_list("id", flat=True)[:RETENTION_DELETE_BATCH_SIZE]):
        _, by_model = model.objects.unscoped().filter(id__in=ids).delete()
        for label, count in by_model.items():
            totals[label] += count
        _heartbeat()
    return totals


@activity.defn
async def cleanup_check_runs_activity() -> CleanupOutcome:
    return await sync_to_async(_cleanup)()


def _cleanup() -> CleanupOutcome:
    """Retention sweep across every team, which is why it uses the unscoped manager."""
    now = datetime.now(UTC)
    runs = DataQualityCheckRun.objects.unscoped()

    queries_cleared = (
        runs.filter(created_at__lt=now - timedelta(days=COMPILED_QUERY_RETENTION_DAYS))
        .exclude(compiled_query="")
        .update(compiled_query="")
    )

    dead = _sweep_dead_subjects(now)

    has_newer_run = runs.filter(quality_check_id=OuterRef("quality_check_id"), created_at__gt=OuterRef("created_at"))
    expired_runs = runs.filter(created_at__lt=now - timedelta(days=CHECK_RUN_RETENTION_DAYS)).filter(
        Q(quality_check_id__isnull=True) | Exists(has_newer_run)
    )
    runs_deleted = _delete_in_batches(expired_runs).get(DataQualityCheckRun._meta.label, 0)

    backs_a_run = DataQualityCheckRun.objects.unscoped().filter(suite_run_id=OuterRef("id"))
    expired_suites = (
        DataQualitySuiteRun.objects.unscoped()
        .filter(created_at__lt=now - timedelta(days=SUITE_RUN_RETENTION_DAYS))
        .filter(~Exists(backs_a_run))
    )
    suites_deleted = _delete_in_batches(expired_suites).get(DataQualitySuiteRun._meta.label, 0)

    stale_failed = (
        DataQualitySuiteRun.objects.unscoped()
        .filter(status=SuiteRunStatus.RUNNING, created_at__lt=now - timedelta(hours=STALE_SUITE_HOURS))
        .update(status=SuiteRunStatus.FAILED, error=STALE_SUITE_ERROR, finished_at=now, updated_at=now)
    )

    outcome = CleanupOutcome(
        compiled_queries_cleared=queries_cleared,
        checks_deleted=dead.checks_deleted,
        check_runs_deleted=runs_deleted + dead.check_runs_deleted,
        suite_runs_deleted=suites_deleted + dead.suite_runs_deleted,
        stale_suites_failed=stale_failed,
    )
    LOGGER.info(
        "Cleaned up data quality history",
        queries_cleared=outcome.compiled_queries_cleared,
        checks_deleted=outcome.checks_deleted,
        runs_deleted=outcome.check_runs_deleted,
        suites_deleted=outcome.suite_runs_deleted,
        stale_suites_failed=outcome.stale_suites_failed,
    )
    return outcome


@frozen
class _LiveSubjects:
    """The warehouse objects a team still has, by id."""

    table_ids: frozenset[UUID]
    view_ids: frozenset[UUID]

    def alive_q(self, table_field: str = "subject_uuid", view_field: str = "subject_uuid") -> Q:
        # An explicit predicate per known kind, so a row of a kind this sweep does not know reads as
        # dead rather than as alive by default. Runs and suites denormalize the subject into one
        # column; a check carries it as whichever of its two foreign keys is set.
        return Q(**{"subject_type": SubjectType.TABLE, f"{table_field}__in": self.table_ids}) | Q(
            **{"subject_type": SubjectType.VIEW, f"{view_field}__in": self.view_ids}
        )


def _sweep_dead_subjects(now: datetime) -> CleanupOutcome:
    """Delete the rows whose warehouse subject no longer exists, team by team.

    Deleting a table or view takes its object-level denial with it, so nothing left can show a
    restricted member was allowed the rows a check ran over. The gates withhold such rows meanwhile;
    this is what closes that window instead of leaving it open for the life of the history.

    Only the subject a row declares is judged. A live check that references a subject which died
    stays, because an admin can still see it and repoint it.
    """
    checks = runs = suites = 0
    for team_id in _teams_with_history():
        live = _live_subjects(team_id)
        grace = now - timedelta(hours=SUBJECT_GRACE_HOURS)
        checks += _delete_dead_checks(team_id, live, grace)
        runs += _delete_dead_runs(team_id, live, grace)
        suites += _delete_dead_suites(team_id, live, grace)
        _heartbeat()
    return CleanupOutcome(checks_deleted=checks, check_runs_deleted=runs, suite_runs_deleted=suites)


def _teams_with_history() -> set[int]:
    return {
        team_id
        for manager in (DataQualityCheck.objects, DataQualityCheckRun.objects, DataQualitySuiteRun.objects)
        for team_id in manager.unscoped().values_list("team_id", flat=True).distinct()
    }


def _live_subjects(team_id: int) -> _LiveSubjects:
    return _LiveSubjects(
        table_ids=frozenset(warehouse_facade.all_queryable_table_names(team_id)),
        view_ids=frozenset(UUID(view_id) for view_id in data_modeling_facade.all_saved_query_names(team_id)),
    )


def _delete_dead_checks(team_id: int, live: _LiveSubjects, grace: datetime) -> int:
    alive = live.alive_q(table_field="table_id", view_field="saved_query_id")
    dead = DataQualityCheck.objects.for_team(team_id).filter(created_at__lt=grace).exclude(alive)
    return _delete_in_batches(dead).get(DataQualityCheck._meta.label, 0)


def _delete_dead_runs(team_id: int, live: _LiveSubjects, grace: datetime) -> int:
    dead = DataQualityCheckRun.objects.for_team(team_id).filter(created_at__lt=grace).exclude(live.alive_q())
    deleted = 0
    while batch := list(dead.values_list("id", "suite_run_id", "status")[:RETENTION_DELETE_BATCH_SIZE]):
        with transaction.atomic():
            _decrement_suite_counters((suite_run_id, status) for _, suite_run_id, status in batch)
            _, by_model = (
                DataQualityCheckRun.objects.unscoped().filter(id__in=[run_id for run_id, _, _ in batch]).delete()
            )
        deleted += by_model.get(DataQualityCheckRun._meta.label, 0)
        _heartbeat()
    return deleted


def _decrement_suite_counters(deleted: Iterable[tuple[UUID, str]]) -> None:
    """Take each deleted run back out of its suite's outcome counters.

    A sweep covers several subjects, so its suite survives one of them dying. Counters left at their
    original totals would still report the deleted run, which is the count oracle over unreadable
    rows this whole layer exists to close -- rebuilt by subtraction.
    """
    tally: dict[UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for suite_run_id, status in deleted:
        if column := _COUNTER_COLUMNS.get(status):
            tally[suite_run_id][column] += 1
    for suite_run_id, columns in tally.items():
        DataQualitySuiteRun.objects.unscoped().filter(id=suite_run_id).update(
            **{column: Greatest(F(column) - count, Value(0)) for column, count in columns.items()}
        )


def _delete_dead_suites(team_id: int, live: _LiveSubjects, grace: datetime) -> int:
    backs_a_run = DataQualityCheckRun.objects.unscoped().filter(suite_run_id=OuterRef("id"))
    dead = (
        DataQualitySuiteRun.objects.for_team(team_id)
        .filter(created_at__lt=grace, subject_uuid__isnull=False)
        .exclude(live.alive_q())
        .filter(~Exists(backs_a_run))
    )
    return _delete_in_batches(dead).get(DataQualitySuiteRun._meta.label, 0)
