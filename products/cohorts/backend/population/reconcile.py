"""Finds and repairs static cohorts whose two membership stores disagree."""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone as django_timezone

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE
from posthog.models.person.util import get_person_ids_and_uuids_by_uuids
from posthog.models.utils import uuid7
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.schema_enums import ProductKey

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import (
    CohortPopulationOperation,
    CohortPopulationSource,
    CohortPopulationStatus,
)
from products.cohorts.backend.models.util import list_cohort_member_ids
from products.cohorts.backend.population import operation as operation_lifecycle
from products.cohorts.backend.population.progress import PopulationProgress

logger = structlog.get_logger(__name__)

CH_PAGE_SIZE = 10_000


@frozen
class MembershipAudit:
    """What one cohort's two stores hold, and how far apart they are."""

    cohort_id: int
    team_id: int
    name: str
    clickhouse_members: int
    resolvable_members: int
    postgres_members: int
    missing_from_postgres: int
    unresolvable_members: int
    """ClickHouse UUIDs that resolve to nobody — deleted or merged people, never repairable."""

    import_complete: bool | None
    """Whether the run that filled this cohort recorded a finished import. Independent of the
    drift above: a repaired cohort with an unfinished import is still missing what was never
    uploaded, and only the person who has the file can fix that."""

    @property
    def needs_repair(self) -> bool:
        return self.missing_from_postgres > 0


def audit_cohorts(cohorts: list[Cohort]) -> list[MembershipAudit]:
    return [audit_cohort(cohort) for cohort in cohorts]


def audit_cohort(cohort: Cohort) -> MembershipAudit:
    postgres_ids = set(list_cohort_member_ids(cohort.team_id, cohort.pk))
    clickhouse_members = resolvable_members = missing = 0
    for uuids in _clickhouse_member_pages(cohort):
        with personhog_caller_tag("cohorts/reconcile-audit"):
            resolvable = get_person_ids_and_uuids_by_uuids(cohort.team_id, uuids)
        clickhouse_members += len(uuids)
        resolvable_members += len(resolvable)
        missing += sum(person_id not in postgres_ids for person_id, _ in resolvable)
    population = (
        CohortPopulationOperation.objects.unscoped()
        .filter(cohort_id=cohort.pk)
        .exclude(source=CohortPopulationSource.RECONCILE)
        .order_by("-created_at")
        .first()
    )
    return MembershipAudit(
        cohort_id=cohort.pk,
        team_id=cohort.team_id,
        name=cohort.name or "",
        clickhouse_members=clickhouse_members,
        resolvable_members=resolvable_members,
        postgres_members=len(postgres_ids),
        missing_from_postgres=missing,
        unresolvable_members=clickhouse_members - resolvable_members,
        import_complete=population.status == CohortPopulationStatus.COMPLETED if population else None,
    )


def audit_candidates(*, team_ids: list[int] | None, since, after_cohort_id: int, limit: int) -> list[Cohort]:
    """Static cohorts to audit, ordered by id so a run can resume where the last one stopped."""
    queryset = Cohort.objects.filter(is_static=True, deleted=False, pk__gt=after_cohort_id)
    if team_ids:
        queryset = queryset.filter(team_id__in=team_ids)
    if since is not None:
        queryset = queryset.filter(
            Q(created_at__gte=since) | Q(last_calculation__gte=since) | Q(last_error_at__gte=since)
        )
    return list(queryset.order_by("pk")[:limit])


def start_reconciliation(cohort: Cohort) -> CohortPopulationOperation:
    """Admit an operation that writes the cohort's ClickHouse membership into Postgres."""
    return operation_lifecycle.admit(
        operation_id=uuid7(),
        cohort=cohort,
        team_id=cohort.team_id,
        source=CohortPopulationSource.RECONCILE,
        progress=PopulationProgress(source_materialized=True),
    )


def _clickhouse_member_pages(cohort: Cohort):
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    cursor = "00000000-0000-0000-0000-000000000000"
    while True:
        # nosemgrep: clickhouse-fstring-param-audit - table name from constant, values parameterized
        rows = sync_execute(
            f"SELECT DISTINCT person_id FROM {PERSON_STATIC_COHORT_TABLE} "
            "WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND person_id > %(cursor)s "
            "ORDER BY person_id LIMIT %(limit)s",
            {
                "team_id": cohort.team_id,
                "cohort_id": cohort.pk,
                "cursor": cursor,
                "limit": CH_PAGE_SIZE,
            },
        )
        if not rows:
            return
        yield [str(row[0]) for row in rows]
        cursor = str(rows[-1][0])


def log_audit(audit: MembershipAudit) -> None:
    logger.info(
        "cohort_membership_audit",
        cohort_id=audit.cohort_id,
        team_id=audit.team_id,
        clickhouse_members=audit.clickhouse_members,
        resolvable_members=audit.resolvable_members,
        postgres_members=audit.postgres_members,
        missing_from_postgres=audit.missing_from_postgres,
        unresolvable_members=audit.unresolvable_members,
        import_complete=audit.import_complete,
        audited_at=django_timezone.now().isoformat(),
    )
