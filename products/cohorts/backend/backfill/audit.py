"""Find realtime cohorts whose readiness stamp vouches for a membership table that does not hold their members.

A readiness stamp says a backfill of the current definition completed once. It does not say the
behavioral cohorts database's ``cohort_membership`` table holds the cohort's members, and a pipeline
bug can stamp a cohort over an empty or partial table. Readers that route the cohort to the table
then treat real members as non-members, and nothing reports it.

This module compares each stamped cohort's realtime member count against its batch population, and
can rebuild the cohorts it flags. The batch population is ``Cohort.count``: the batch calculation
writes ``count(DISTINCT person_id)`` of ClickHouse ``cohortpeople`` at the new ``version`` in the
same update as that version, so it is the population the cohort page shows, read with no ClickHouse
query. It is only as fresh as ``last_calculation``, which the report shows next to it.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q

import psycopg
import structlog

from posthog.dataclasses import frozen

from products.cohorts.backend.backfill.finalize import invalidate_team_readiness_caches
from products.cohorts.backend.backfill.runs import (
    check_run_preconditions,
    create_person_team_backfill_run,
    create_team_backfill_run,
)
from products.cohorts.backend.backfill.sizing import PersonSeedEstimateScanCapExceeded
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.leaf_shape import walk_filter_leaves

logger = structlog.get_logger(__name__)

AuditClassification = Literal["zero_members", "divergent", "ok", "no_batch", "unreadable"]
FLAGGED_CLASSIFICATIONS: frozenset[AuditClassification] = frozenset({"zero_members", "divergent"})

# Realtime and batch membership legitimately differ: the batch count is as old as its last
# calculation, and a behavioral backfill covers history only up to the seeder's lookback cap. The
# default only flags a table that misses or adds at least half of the batch population.
DEFAULT_DIVERGENCE_THRESHOLD = 0.5

MEMBERSHIP_COUNT_STATEMENT_TIMEOUT_MS = 30_000
MEMBERSHIP_CONNECT_TIMEOUT_SECONDS = 10

# Readers trust only `in_cohort = true` rows: reconcile also writes `false` rows for non-members.
_MEMBER_COUNT_SQL = "SELECT count(*) FROM cohort_membership WHERE team_id = %s AND cohort_id = %s AND in_cohort"

# Every stamp that can route a cohort to the membership table, in Django or in the flags service's
# stamp policies. The legacy calculation stamp is one of them under `events_or_calculation_stamp`.
_STAMP_FIELDS = ("last_backfill_events_at", "last_backfill_person_properties_at", "last_realtime_cohort_calculation_at")

# One team run per kind, in this order, so a behavioral refusal never hides a person outcome.
_REBUILD_KINDS = (CohortBackfillKind.BEHAVIORAL, CohortBackfillKind.PERSON_PROPERTY)


class MembershipStoreNotConfigured(Exception):
    pass


class MembershipCounter(Protocol):
    def count_members(self, team_id: int, cohort_id: int) -> int: ...


class RealtimeMembershipReader:
    """Counts members in ``cohort_membership`` over one lazily opened, read-only connection.

    The connection is not a Django database, so no ORM query can reach the behavioral cohorts
    database by accident, and the audit is the only code that can read it.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection: psycopg.Connection[Any] | None = None

    def count_members(self, team_id: int, cohort_id: int) -> int:
        connection = self._connect()
        with connection.transaction(), connection.cursor() as cursor:
            # `set_config(..., true)` is transaction-local, like SET LOCAL, so it holds through a
            # transaction-pooling PgBouncer and never leaks onto a pooled server connection.
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)", [str(MEMBERSHIP_COUNT_STATEMENT_TIMEOUT_MS)]
            )
            cursor.execute(_MEMBER_COUNT_SQL, [team_id, cohort_id])
            row = cursor.fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _connect(self) -> psycopg.Connection[Any]:
        if self._connection is None:
            connection = psycopg.connect(self._dsn, connect_timeout=MEMBERSHIP_CONNECT_TIMEOUT_SECONDS)
            # Every transaction opens with BEGIN READ ONLY, so a write fails even when the DSN's
            # role is wider than it should be.
            connection.read_only = True
            self._connection = connection
        return self._connection


@contextmanager
def open_realtime_membership_reader() -> Iterator[RealtimeMembershipReader]:
    dsn = settings.BEHAVIORAL_COHORTS_READ_DATABASE_URL
    if not dsn:
        raise MembershipStoreNotConfigured(
            "BEHAVIORAL_COHORTS_READ_DATABASE_URL is not set, so the audit cannot read cohort_membership. "
            "Set it to a read-only DSN for the behavioral cohorts database and run the audit again."
        )
    reader = RealtimeMembershipReader(dsn)
    try:
        yield reader
    finally:
        reader.close()


@frozen
class ReadinessStamps:
    events_at: datetime | None
    person_properties_at: datetime | None
    realtime_calculation_at: datetime | None

    @classmethod
    def of(cls, cohort: Cohort) -> "ReadinessStamps":
        return cls(
            events_at=cohort.last_backfill_events_at,
            person_properties_at=cohort.last_backfill_person_properties_at,
            realtime_calculation_at=cohort.last_realtime_cohort_calculation_at,
        )

    def as_fields(self) -> dict[str, datetime | None]:
        return dict(zip(_STAMP_FIELDS, (self.events_at, self.person_properties_at, self.realtime_calculation_at)))

    def set_names(self) -> tuple[str, ...]:
        return tuple(name for name, value in self.as_fields().items() if value is not None)


@frozen
class CohortMembershipAuditRow:
    cohort_id: int
    name: str
    classification: AuditClassification
    # Two or more leaves, or a cohort reference: the shapes a recomposition gap leaves unbuilt.
    composed: bool
    realtime_members: int | None
    batch_members: int | None
    batch_calculated_at: datetime | None
    # The backfill kinds the current filters need stamped, which a rebuild has to run again.
    needed_kinds: tuple[str, ...]
    stamps: ReadinessStamps
    detail: str = ""

    @property
    def flagged(self) -> bool:
        return self.classification in FLAGGED_CLASSIFICATIONS


@frozen
class MembershipAuditReport:
    team_id: int
    threshold: float
    rows: tuple[CohortMembershipAuditRow, ...]
    # Requested ids that are not stamped realtime cohorts of the team, so nothing was compared.
    skipped_cohort_ids: tuple[int, ...]

    @property
    def flagged(self) -> tuple[CohortMembershipAuditRow, ...]:
        return tuple(row for row in self.rows if row.flagged)


@frozen
class RebuildRunOutcome:
    kind: str
    cohort_ids: tuple[int, ...]
    run_id: UUID | None
    refusal: str = ""


@frozen
class StampClearOutcome:
    cleared_cohort_ids: tuple[int, ...]
    # Cohorts whose stamps changed after the audit read them, for example a finalizer pass that
    # stamped a fresh run. They are left alone, so the audit never clears a stamp it did not judge.
    moved_cohort_ids: tuple[int, ...]


def classify_membership(
    *, realtime_members: int | None, batch_members: int | None, threshold: float
) -> AuditClassification:
    if realtime_members is None:
        return "unreadable"
    if batch_members is None:
        return "no_batch"
    if batch_members == 0:
        return "ok" if realtime_members == 0 else "divergent"
    if realtime_members == 0:
        return "zero_members"
    if abs(realtime_members - batch_members) / batch_members > threshold:
        return "divergent"
    return "ok"


def is_composed(filters: dict[str, Any] | None) -> bool:
    leaves = list(walk_filter_leaves((filters or {}).get("properties")))
    return len(leaves) >= 2 or any(leaf.get("type") == "cohort" for leaf in leaves)


def audit_team_membership(
    team_id: int,
    *,
    reader: MembershipCounter,
    cohort_ids: Sequence[int] | None = None,
    threshold: float = DEFAULT_DIVERGENCE_THRESHOLD,
) -> MembershipAuditReport:
    if threshold < 0:
        raise ValueError("threshold must be 0 or more")

    any_stamp = (
        Q(last_backfill_events_at__isnull=False)
        | Q(last_backfill_person_properties_at__isnull=False)
        | Q(last_realtime_cohort_calculation_at__isnull=False)
    )
    queryset = Cohort.objects.filter(
        any_stamp, team_id=team_id, cohort_type=CohortType.REALTIME, deleted=False, is_static=False
    )
    if cohort_ids is not None:
        queryset = queryset.filter(id__in=cohort_ids)
    cohorts = list(
        queryset.only(
            "id", "name", "filters", "count", "version", "last_calculation", "cohort_type", *_STAMP_FIELDS
        ).order_by("id")
    )

    rows = tuple(_audit_cohort(team_id, cohort, reader=reader, threshold=threshold) for cohort in cohorts)
    audited_ids = {cohort.id for cohort in cohorts}
    skipped = tuple(sorted(set(cohort_ids or ()) - audited_ids))
    return MembershipAuditReport(team_id=team_id, threshold=threshold, rows=rows, skipped_cohort_ids=skipped)


def _audit_cohort(
    team_id: int, cohort: Cohort, *, reader: MembershipCounter, threshold: float
) -> CohortMembershipAuditRow:
    detail = ""
    realtime_members: int | None
    try:
        realtime_members = reader.count_members(team_id, cohort.id)
    except psycopg.errors.QueryCanceled:
        # One oversized cohort must not end the audit of the rest.
        realtime_members = None
        detail = f"count exceeded the {MEMBERSHIP_COUNT_STATEMENT_TIMEOUT_MS} ms statement timeout"

    # A count without a version or calculation time was not written by a finished batch calculation.
    has_batch = cohort.count is not None and cohort.version is not None and cohort.last_calculation is not None
    batch_members = cohort.count if has_batch else None
    return CohortMembershipAuditRow(
        cohort_id=cohort.id,
        name=cohort.name or "",
        classification=classify_membership(
            realtime_members=realtime_members, batch_members=batch_members, threshold=threshold
        ),
        composed=is_composed(cohort.filters),
        realtime_members=realtime_members,
        batch_members=batch_members,
        batch_calculated_at=cohort.last_calculation if has_batch else None,
        needed_kinds=tuple(sorted(cohort._required_backfill_stamps())),
        stamps=ReadinessStamps.of(cohort),
        detail=detail,
    )


def clear_readiness_stamps(report: MembershipAuditReport) -> StampClearOutcome:
    """Null every readiness stamp of the flagged cohorts, so readers stop routing them to the table.

    The write bypasses ``Cohort.save()``, so it supersedes no run and moves no shape hash: a rebuild
    run of the unchanged definition can still stamp the cohort again.
    """
    cleared: list[int] = []
    moved: list[int] = []
    with transaction.atomic():
        for row in report.flagged:
            # Fenced on the stamps the audit read. A stamp written since belongs to a backfill this
            # audit never compared, so the update matches nothing and the cohort keeps it.
            updated = Cohort.objects.filter(id=row.cohort_id, team_id=report.team_id, **row.stamps.as_fields()).update(
                **dict.fromkeys(_STAMP_FIELDS, None)
            )
            (cleared if updated else moved).append(row.cohort_id)

    if cleared:
        logger.info("cohort_membership_audit_stamps_cleared", team_id=report.team_id, cohort_ids=cleared)
        invalidate_team_readiness_caches(report.team_id)
    return StampClearOutcome(cleared_cohort_ids=tuple(cleared), moved_cohort_ids=tuple(moved))


def create_rebuild_runs(report: MembershipAuditReport, *, person_horizon_days: int) -> list[RebuildRunOutcome]:
    """One team run per backfill kind the flagged cohorts need, through the operator creators.

    A creator refusal, such as an occupied run slot, comes back as the outcome's ``refusal``.
    """
    outcomes: list[RebuildRunOutcome] = []
    for kind in _REBUILD_KINDS:
        cohort_ids = tuple(row.cohort_id for row in report.flagged if kind in row.needed_kinds)
        if cohort_ids:
            outcomes.append(_create_rebuild_run(report.team_id, kind, cohort_ids, person_horizon_days))
    return outcomes


def _create_rebuild_run(
    team_id: int, kind: CohortBackfillKind, cohort_ids: tuple[int, ...], person_horizon_days: int
) -> RebuildRunOutcome:
    trigger = CohortBackfillTrigger.TEAM_ENABLEMENT
    try:
        if kind == CohortBackfillKind.BEHAVIORAL:
            # The behavioral creator records a run as `blocked` instead of refusing, and nothing
            # moves a run out of `blocked`, so refuse first like the operator command does.
            _, missing = check_run_preconditions()
            if missing:
                return RebuildRunOutcome(
                    kind=kind,
                    cohort_ids=cohort_ids,
                    run_id=None,
                    refusal=f"Missing operator attestations: {', '.join(missing)}",
                )
            run = create_team_backfill_run(team_id, trigger, cohort_ids)
        else:
            run = create_person_team_backfill_run(team_id, trigger, person_horizon_days, cohort_ids)
    except IntegrityError:
        return RebuildRunOutcome(
            kind=kind,
            cohort_ids=cohort_ids,
            run_id=None,
            refusal=f"Team {team_id} already has an active team backfill run ({kind})",
        )
    # The pinning cap error is a ValueError too.
    except (ValueError, PersonSeedEstimateScanCapExceeded) as error:
        return RebuildRunOutcome(kind=kind, cohort_ids=cohort_ids, run_id=None, refusal=str(error))

    logger.info(
        "cohort_membership_audit_rebuild_run_created",
        team_id=team_id,
        run_id=str(run.id),
        backfill_kind=kind,
        cohort_ids=list(cohort_ids),
    )
    return RebuildRunOutcome(kind=kind, cohort_ids=cohort_ids, run_id=run.id)
