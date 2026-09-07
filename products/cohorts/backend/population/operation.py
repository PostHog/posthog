"""The lifecycle of a static cohort population operation."""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone as django_timezone

import structlog

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import (
    ACTIVE_COHORT_POPULATION_STATUSES,
    UNRESOLVED_COHORT_POPULATION_STATUSES,
    CohortPopulationOperation,
    CohortPopulationPhase,
    CohortPopulationSource,
    CohortPopulationStatus,
)
from products.cohorts.backend.models.util import CohortErrorCode
from products.cohorts.backend.population.input_store import delete_input
from products.cohorts.backend.population.progress import PopulationProgress

logger = structlog.get_logger(__name__)

RETRY_INITIAL_BACKOFF_SECONDS = 60
RETRY_MAX_BACKOFF_SECONDS = 1800

_STARTING_PHASE = {
    CohortPopulationSource.LIST: CohortPopulationPhase.WRITING_MEMBERSHIP,
    CohortPopulationSource.QUERY: CohortPopulationPhase.MATERIALIZING_SOURCE,
    CohortPopulationSource.FILTERS: CohortPopulationPhase.MATERIALIZING_SOURCE,
    CohortPopulationSource.FEATURE_FLAG: CohortPopulationPhase.MATERIALIZING_SOURCE,
    CohortPopulationSource.RECONCILE: CohortPopulationPhase.SYNCHRONIZING,
}


class CohortPopulationConflict(Exception):
    """The cohort already has an unresolved operation, so this one cannot be admitted."""

    def __init__(self, operation: CohortPopulationOperation) -> None:
        super().__init__(f"cohort {operation.cohort_id} already has operation {operation.pk} in {operation.status}")
        self.operation = operation


def unresolved_operation_for(cohort_id: int) -> CohortPopulationOperation | None:
    return (
        CohortPopulationOperation.objects.unscoped()
        .filter(cohort_id=cohort_id, status__in=UNRESOLVED_COHORT_POPULATION_STATUSES)
        .first()
    )


def latest_operation_for(cohort_id: int) -> CohortPopulationOperation | None:
    return CohortPopulationOperation.objects.unscoped().filter(cohort_id=cohort_id).order_by("-created_at").first()


def admit(
    *,
    operation_id: UUID,
    cohort: Cohort,
    team_id: int,
    source: CohortPopulationSource,
    input_manifest: dict[str, Any] | None = None,
    created_by_id: int | None = None,
    progress: PopulationProgress | None = None,
    source_config: dict[str, Any] | None = None,
) -> CohortPopulationOperation:
    """Record an operation and mark the cohort as calculating, in one transaction."""
    with transaction.atomic():
        Cohort.objects.select_for_update().get(pk=cohort.pk, team_id=team_id, deleted=False, is_static=True)
        existing = unresolved_operation_for(cohort.pk)
        if existing is not None:
            raise CohortPopulationConflict(existing)
        operation = CohortPopulationOperation.objects.for_team(team_id).create(
            id=operation_id,
            team_id=team_id,
            cohort=cohort,
            created_by_id=created_by_id,
            source=source,
            source_config=source_config or {},
            phase=_STARTING_PHASE[source],
            status=CohortPopulationStatus.PENDING,
            input_manifest=input_manifest,
            input_expires_at=_failed_input_expiry(),
            progress=(progress or PopulationProgress()).to_json(),
        )
        Cohort.objects.filter(pk=cohort.pk).update(is_calculating=True)

    logger.info(
        "cohort_population_admitted",
        operation_id=str(operation.pk),
        cohort_id=cohort.pk,
        team_id=team_id,
        source=source,
    )
    return operation


def claim(operation_id: UUID | str, *, worker: str) -> CohortPopulationOperation | None:
    """Take ownership of an operation for one work unit, or return None if it is not claimable."""
    now = django_timezone.now()
    lease = timedelta(seconds=settings.COHORT_POPULATION_LEASE_SECONDS)

    with transaction.atomic():
        operation = CohortPopulationOperation.objects.unscoped().select_for_update().filter(pk=operation_id).first()
        if operation is None:
            return None
        if operation.status not in ACTIVE_COHORT_POPULATION_STATUSES:
            return None
        if (
            operation.next_attempt_at is not None
            and operation.next_attempt_at > now
            and operation.abandon_requested_at is None
        ):
            return None
        if (
            operation.status == CohortPopulationStatus.RUNNING
            and operation.lease_expires_at is not None
            and operation.lease_expires_at > now
        ):
            return None

        if operation.status == CohortPopulationStatus.RUNNING:
            operation.attempts += 1
            if operation.attempts > operation.max_attempts:
                operation.status = CohortPopulationStatus.FAILED
                operation.error_code = CohortErrorCode.UNKNOWN
                operation.claim_token = None
                operation.lease_expires_at = None
                operation.finished_at = now
                operation.input_expires_at = _failed_input_expiry()
                operation.save()
                Cohort.objects.filter(pk=operation.cohort_id).update(**_failure_fields())
                return None
        operation.status = CohortPopulationStatus.RUNNING
        operation.claim_token = uuid4()
        operation.claimed_by = worker[:255]
        operation.claimed_at = now
        operation.lease_expires_at = now + lease
        operation.next_attempt_at = None
        operation.save(
            update_fields=[
                "status",
                "claim_token",
                "claimed_by",
                "claimed_at",
                "lease_expires_at",
                "next_attempt_at",
                "attempts",
                "updated_at",
            ]
        )

    return operation


def release(operation: CohortPopulationOperation) -> bool:
    """Hand an unfinished operation back to the queue, so the next worker need not wait out the lease."""
    return _guarded_update(
        operation,
        {
            "status": CohortPopulationStatus.PENDING,
            "claim_token": None,
            "lease_expires_at": None,
            "dispatched_at": None,
        },
    )


def checkpoint(
    operation: CohortPopulationOperation,
    *,
    progress: PopulationProgress,
    phase: CohortPopulationPhase | None = None,
    input_manifest: dict[str, Any] | None = None,
) -> bool:
    """Record progress for the claiming attempt, extending its lease."""
    fields: dict[str, Any] = {
        "progress": progress.to_json(),
        "lease_expires_at": django_timezone.now() + timedelta(seconds=settings.COHORT_POPULATION_LEASE_SECONDS),
    }
    if phase is not None:
        fields["phase"] = phase
    if input_manifest is not None:
        fields["input_manifest"] = input_manifest

    updated = _guarded_update(operation, fields)
    if updated:
        operation.progress = fields["progress"]
        if phase is not None:
            operation.phase = phase
        if input_manifest is not None:
            operation.input_manifest = input_manifest
    return updated


def complete(operation: CohortPopulationOperation, *, count: int | None = None) -> bool:
    """Mark the operation successful and start the short retention clock on its input."""
    cohort_fields: dict[str, Any] = {
        "is_calculating": False,
        "last_calculation": django_timezone.now(),
        "errors_calculating": 0,
    }
    if count is not None:
        cohort_fields["count"] = count
    if operation.source == CohortPopulationSource.LIST and operation.input_manifest is not None:
        cohort_fields.update(
            last_import_total_count=operation.input_manifest["total"],
            last_import_unmatched_count=PopulationProgress.from_json(operation.progress).unmatched,
        )
    updated = _guarded_update(
        operation,
        {
            "status": CohortPopulationStatus.COMPLETED,
            "phase": CohortPopulationPhase.DONE,
            "error_code": "",
            "claim_token": None,
            "lease_expires_at": None,
            "finished_at": django_timezone.now(),
            "input_expires_at": _completed_input_expiry(),
        },
        cohort_fields=cohort_fields,
        completing=True,
    )
    if updated:
        logger.info(
            "cohort_population_completed",
            operation_id=str(operation.pk),
            cohort_id=operation.cohort_id,
            team_id=operation.team_id,
        )
    return updated


def schedule_retry(operation: CohortPopulationOperation, *, error_code: CohortErrorCode) -> bool:
    """Release the claim and set the next attempt, or fail the operation once the budget is spent."""
    attempts = operation.attempts + 1
    exhausted = attempts > operation.max_attempts

    fields: dict[str, Any] = {
        "attempts": attempts,
        "error_code": error_code.value,
        "claim_token": None,
        "lease_expires_at": None,
    }
    if exhausted:
        fields |= {
            "status": CohortPopulationStatus.FAILED,
            "next_attempt_at": None,
            "finished_at": django_timezone.now(),
            "input_expires_at": _failed_input_expiry(),
        }
    else:
        fields |= {
            "status": CohortPopulationStatus.RETRY_SCHEDULED,
            "next_attempt_at": django_timezone.now() + timedelta(seconds=_backoff_seconds(attempts)),
        }

    updated = _guarded_update(operation, fields, cohort_fields=_failure_fields() if exhausted else None)
    if updated:
        logger.warning(
            "cohort_population_attempt_failed",
            operation_id=str(operation.pk),
            cohort_id=operation.cohort_id,
            team_id=operation.team_id,
            attempts=attempts,
            exhausted=exhausted,
            error_code=error_code.value,
        )
    return updated


def fail_permanently(operation: CohortPopulationOperation, *, error_code: CohortErrorCode) -> bool:
    """End the operation without spending the remaining budget, for an error retrying cannot fix."""
    updated = _guarded_update(
        operation,
        {
            "status": CohortPopulationStatus.FAILED,
            "attempts": operation.attempts + 1,
            "error_code": error_code.value,
            "claim_token": None,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "finished_at": django_timezone.now(),
            "input_expires_at": _failed_input_expiry(),
        },
        cohort_fields=_failure_fields(),
    )
    if updated:
        logger.warning(
            "cohort_population_failed",
            operation_id=str(operation.pk),
            cohort_id=operation.cohort_id,
            team_id=operation.team_id,
            error_code=error_code.value,
        )
    return updated


def request_abandon(operation: CohortPopulationOperation) -> None:
    """Ask the run to stop. The runner does the stopping, so an in-flight attempt settles first."""
    with transaction.atomic():
        current = CohortPopulationOperation.objects.unscoped().select_for_update().get(pk=operation.pk)
        if current.status not in UNRESOLVED_COHORT_POPULATION_STATUSES:
            return
        current.abandon_requested_at = current.abandon_requested_at or django_timezone.now()
        if current.status == CohortPopulationStatus.FAILED:
            current.status = CohortPopulationStatus.PENDING
            current.attempts = 0
        current.next_attempt_at = None
        current.dispatched_at = None
        current.save(
            update_fields=[
                "abandon_requested_at",
                "status",
                "attempts",
                "next_attempt_at",
                "dispatched_at",
                "updated_at",
            ]
        )
        Cohort.objects.filter(pk=current.cohort_id).update(is_calculating=True)


def abandon(operation: CohortPopulationOperation, *, count: int | None = None) -> bool:
    """Close the operation out, keeping whatever membership was already written."""
    updated = _guarded_update(
        operation,
        {
            "status": CohortPopulationStatus.ABANDONED,
            "claim_token": None,
            "lease_expires_at": None,
            "next_attempt_at": None,
            "finished_at": django_timezone.now(),
            "input_expires_at": _completed_input_expiry(),
        },
        cohort_fields={**_failure_fields(), **({"count": count} if count is not None else {})},
    )
    if updated:
        logger.warning(
            "cohort_population_abandoned",
            operation_id=str(operation.pk),
            cohort_id=operation.cohort_id,
            team_id=operation.team_id,
        )
    return updated


def reopen_for_retry(operation: CohortPopulationOperation, *, requested_by_id: int | None) -> None:
    """Put a failed operation back in the queue with its progress intact and a fresh budget."""
    with transaction.atomic():
        current = CohortPopulationOperation.objects.unscoped().select_for_update().get(pk=operation.pk)
        if current.status != CohortPopulationStatus.FAILED:
            raise CohortPopulationConflict(current)
        if not input_looks_available(current):
            raise ValueError("Population input is unavailable")
        CohortPopulationOperation.objects.unscoped().filter(pk=current.pk).update(
            status=CohortPopulationStatus.PENDING,
            attempts=0,
            next_attempt_at=None,
            claim_token=None,
            claimed_by="",
            lease_expires_at=None,
            dispatched_at=None,
            finished_at=None,
            error_code="",
            input_expires_at=_failed_input_expiry(),
            updated_at=django_timezone.now(),
        )
        Cohort.objects.filter(pk=operation.cohort_id).update(is_calculating=True)
    logger.info(
        "cohort_population_retry_requested",
        operation_id=str(operation.pk),
        cohort_id=operation.cohort_id,
        team_id=operation.team_id,
        requested_by_id=requested_by_id,
    )


def reap_input(operation: CohortPopulationOperation) -> None:
    """Delete the retained identifiers and record that they are gone."""
    with transaction.atomic():
        current = CohortPopulationOperation.objects.unscoped().select_for_update().get(pk=operation.pk)
        if (
            current.status in ACTIVE_COHORT_POPULATION_STATUSES
            or current.input_expires_at is None
            or current.input_expires_at > django_timezone.now()
        ):
            return
        # Retry cannot race deletion after this durable tombstone.
        current.input_deleted_at = current.input_deleted_at or django_timezone.now()
        current.save(update_fields=["input_deleted_at"])
    delete_input(current.input_manifest)
    CohortPopulationOperation.objects.unscoped().filter(pk=current.pk).update(input_manifest=None)


def input_looks_available(operation: CohortPopulationOperation) -> bool:
    if operation.abandon_requested_at is not None or operation.phase in (
        CohortPopulationPhase.SYNCHRONIZING,
        CohortPopulationPhase.FINALIZING,
    ):
        return True
    if operation.source in (
        CohortPopulationSource.QUERY,
        CohortPopulationSource.FILTERS,
        CohortPopulationSource.RECONCILE,
    ):
        return True
    if (
        operation.error_code == CohortErrorCode.INPUT_UNAVAILABLE
        or operation.input_manifest is None
        or operation.input_deleted_at is not None
    ):
        return False
    return operation.input_expires_at is None or operation.input_expires_at > django_timezone.now()


def _failure_fields() -> dict[str, Any]:
    return {
        "is_calculating": False,
        "errors_calculating": F("errors_calculating") + 1,
        "last_error_at": django_timezone.now(),
    }


def _guarded_update(
    operation: CohortPopulationOperation,
    fields: dict[str, Any],
    *,
    cohort_fields: dict[str, Any] | None = None,
    completing: bool = False,
) -> bool:
    if operation.claim_token is None:
        # A cleared token means this attempt already made its terminal move. Matching on NULL here
        # would match the row again and let a second transition overwrite the first.
        return False

    fields["updated_at"] = django_timezone.now()
    with transaction.atomic():
        queryset = CohortPopulationOperation.objects.unscoped().filter(
            pk=operation.pk,
            claim_token=operation.claim_token,
            status=CohortPopulationStatus.RUNNING,
            lease_expires_at__gt=django_timezone.now(),
        )
        if completing:
            queryset = queryset.filter(abandon_requested_at__isnull=True)
        updated = queryset.update(**fields)
        if updated and cohort_fields:
            Cohort.objects.filter(pk=operation.cohort_id, team_id=operation.team_id).update(**cohort_fields)
    if not updated:
        logger.warning(
            "cohort_population_stale_attempt",
            operation_id=str(operation.pk),
            cohort_id=operation.cohort_id,
            team_id=operation.team_id,
        )
        return False
    for name, value in fields.items():
        setattr(operation, name, value)
    return True


def _backoff_seconds(attempt: int) -> float:
    base = min(RETRY_INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)), RETRY_MAX_BACKOFF_SECONDS)
    return min(base + random.uniform(0, base), RETRY_MAX_BACKOFF_SECONDS)


def _failed_input_expiry():
    return django_timezone.now() + timedelta(days=settings.COHORT_POPULATION_FAILED_INPUT_RETENTION_DAYS)


def _completed_input_expiry():
    return django_timezone.now() + timedelta(hours=settings.COHORT_POPULATION_COMPLETED_INPUT_RETENTION_HOURS)
