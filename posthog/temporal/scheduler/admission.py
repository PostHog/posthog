import uuid
import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from django.db import connection, transaction
from django.utils import timezone

from posthog.models.temporal_scheduler import TemporalSchedulerClaim, TemporalSchedulerPermitPool
from posthog.temporal.scheduler.metrics import (
    DEFAULT_SCHEDULER_METRICS,
    ClaimTransition,
    SchedulerMetrics,
    record_scheduler_metrics_safely,
)

MAX_CLAIM_REQUESTS_PER_CALL = 1_000
MAX_CLAIM_ERROR_CHARS = 2_000
MAX_OCCURRENCE_KEY_CHARS = 1_024
MAX_PRUNE_CLAIMS_PER_CALL = 10_000
SCHEDULER_LOCK_TIMEOUT_MS = 5_000

TerminalClaimStatus = Literal["available", "completed", "quarantined"]
ActiveClaimStatus = Literal["reserved", "confirmed"]


class SchedulerOccurrenceHashCollision(RuntimeError):
    pass


class SchedulerClaimInvariantError(RuntimeError):
    pass


@dataclass(frozen=True)
class SchedulerAdmissionLimits:
    max_in_flight: int
    max_in_flight_per_tenant: int
    lease_duration: timedelta


@dataclass(frozen=True)
class SchedulerClaimRequest:
    tenant_key: str
    occurrence_key: str
    workflow_id: str
    # Callers that perform non-transactional side effects before receiving the
    # result can supply a stable token so an activity retry recovers its own
    # RESERVED claim instead of treating it as somebody else's work.
    claim_token: uuid.UUID | None = None


@dataclass(frozen=True)
class SchedulerClaimReservation:
    claim_id: uuid.UUID
    claim_token: uuid.UUID
    tenant_key: str
    occurrence_key: str
    workflow_id: str


@dataclass(frozen=True)
class SchedulerAdmissionResult:
    reservations: tuple[SchedulerClaimReservation, ...]
    already_claimed: int
    deferred_for_capacity: int


@dataclass(frozen=True)
class _HashedRequest:
    request: SchedulerClaimRequest
    occurrence_hash: str


def _occurrence_hash(occurrence_key: str) -> str:
    return hashlib.sha256(occurrence_key.encode("utf-8")).hexdigest()


def _validate_scope(scheduler: str, region: str) -> None:
    if not scheduler.strip() or len(scheduler) > 128:
        raise ValueError("scheduler must contain between 1 and 128 characters")
    if not region.strip() or len(region) > 32:
        raise ValueError("region must contain between 1 and 32 characters")


def _validate_limits(limits: SchedulerAdmissionLimits) -> None:
    if limits.max_in_flight <= 0:
        raise ValueError("max_in_flight must be greater than zero")
    if limits.max_in_flight_per_tenant <= 0:
        raise ValueError("max_in_flight_per_tenant must be greater than zero")
    if limits.max_in_flight_per_tenant > limits.max_in_flight:
        raise ValueError("max_in_flight_per_tenant cannot exceed max_in_flight")
    if limits.lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be greater than zero")


def _validate_request(request: SchedulerClaimRequest) -> None:
    if not request.tenant_key.strip() or len(request.tenant_key) > 128:
        raise ValueError("tenant_key must contain between 1 and 128 characters")
    if not request.occurrence_key.strip() or len(request.occurrence_key) > MAX_OCCURRENCE_KEY_CHARS:
        raise ValueError(f"occurrence_key must contain between 1 and {MAX_OCCURRENCE_KEY_CHARS} characters")
    if not request.workflow_id.strip() or len(request.workflow_id) > 512:
        raise ValueError("workflow_id must contain between 1 and 512 characters")


def _resolve_time(value: datetime | None) -> datetime:
    resolved = value or timezone.now()
    if timezone.is_naive(resolved):
        raise ValueError("scheduler admission datetimes must be timezone-aware")
    return resolved


def _deduplicate_requests(requests: Sequence[SchedulerClaimRequest]) -> tuple[list[_HashedRequest], Counter[str]]:
    if len(requests) > MAX_CLAIM_REQUESTS_PER_CALL:
        raise ValueError(f"requests cannot contain more than {MAX_CLAIM_REQUESTS_PER_CALL} items")

    unique: dict[str, _HashedRequest] = {}
    multiplicities: Counter[str] = Counter()
    for request in requests:
        _validate_request(request)
        occurrence_hash = _occurrence_hash(request.occurrence_key)
        multiplicities[occurrence_hash] += 1
        existing = unique.get(occurrence_hash)
        if existing is None:
            unique[occurrence_hash] = _HashedRequest(request=request, occurrence_hash=occurrence_hash)
        elif existing.request == request:
            continue
        elif existing.request.occurrence_key != request.occurrence_key:
            raise SchedulerOccurrenceHashCollision("two logical occurrences produced the same SHA-256 digest")
        else:
            raise ValueError("one logical occurrence cannot use different tenant or workflow identifiers")
    return list(unique.values()), multiplicities


def _set_scheduler_lock_timeout() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('lock_timeout', %s, TRUE)", [f"{SCHEDULER_LOCK_TIMEOUT_MS}ms"])


def _lock_or_create_pool(scheduler: str, region: str, tenant_key: str) -> TemporalSchedulerPermitPool:
    pool, _ = TemporalSchedulerPermitPool.objects.get_or_create(
        scheduler=scheduler,
        region=region,
        tenant_key=tenant_key,
    )
    return TemporalSchedulerPermitPool.objects.select_for_update().get(id=pool.id)


def _lock_or_create_tenant_pools(
    scheduler: str, region: str, tenant_keys: set[str]
) -> dict[str, TemporalSchedulerPermitPool]:
    if not tenant_keys:
        return {}

    pools = {
        pool.tenant_key: pool
        for pool in TemporalSchedulerPermitPool.objects.select_for_update()
        .filter(scheduler=scheduler, region=region, tenant_key__in=tenant_keys)
        .order_by("tenant_key")
    }
    missing = sorted(tenant_keys - pools.keys())
    if missing:
        created = TemporalSchedulerPermitPool.objects.bulk_create(
            [
                TemporalSchedulerPermitPool(scheduler=scheduler, region=region, tenant_key=tenant_key)
                for tenant_key in missing
            ]
        )
        pools.update({pool.tenant_key: pool for pool in created})
    return pools


def reserve_scheduler_claims(
    *,
    scheduler: str,
    region: str,
    requests: Sequence[SchedulerClaimRequest],
    limits: SchedulerAdmissionLimits,
    now: datetime | None = None,
    metrics: SchedulerMetrics = DEFAULT_SCHEDULER_METRICS,
) -> SchedulerAdmissionResult:
    _validate_scope(scheduler, region)
    _validate_limits(limits)
    hashed_requests, multiplicities = _deduplicate_requests(requests)
    if not hashed_requests:
        return SchedulerAdmissionResult(reservations=(), already_claimed=0, deferred_for_capacity=0)

    claim_time = _resolve_time(now)
    lease_expires_at = claim_time + limits.lease_duration

    with transaction.atomic():
        _set_scheduler_lock_timeout()
        global_pool = _lock_or_create_pool(scheduler, region, "")
        tenant_pools = _lock_or_create_tenant_pools(
            scheduler,
            region,
            {item.request.tenant_key for item in hashed_requests},
        )
        existing_claims = {
            claim.occurrence_hash: claim
            for claim in TemporalSchedulerClaim.objects.select_for_update()
            .filter(
                scheduler=scheduler,
                region=region,
                occurrence_hash__in=[item.occurrence_hash for item in hashed_requests],
            )
            .order_by("id")
        }

        for item in hashed_requests:
            existing = existing_claims.get(item.occurrence_hash)
            if existing is None:
                continue
            if existing.occurrence_key != item.request.occurrence_key:
                raise SchedulerOccurrenceHashCollision(
                    f"logical occurrence digest collision for scheduler {scheduler!r} in region {region!r}"
                )
            if existing.tenant_key != item.request.tenant_key or existing.workflow_id != item.request.workflow_id:
                raise SchedulerClaimInvariantError(
                    "a logical occurrence was requested with different tenant or workflow identifiers"
                )

        global_available = max(limits.max_in_flight - global_pool.in_flight, 0)
        tenant_available = {
            tenant_key: max(limits.max_in_flight_per_tenant - pool.in_flight, 0)
            for tenant_key, pool in tenant_pools.items()
        }
        admitted_per_tenant: Counter[str] = Counter()
        reservations: list[SchedulerClaimReservation] = []
        replayed_reservations = 0
        new_claims: list[TemporalSchedulerClaim] = []
        reused_claims: list[TemporalSchedulerClaim] = []
        already_claimed = 0
        deferred_for_capacity = 0

        for item in hashed_requests:
            request = item.request
            request_count = multiplicities[item.occurrence_hash]
            existing = existing_claims.get(item.occurrence_hash)
            if existing is not None and existing.status != TemporalSchedulerClaim.Status.AVAILABLE:
                if (
                    existing.status == TemporalSchedulerClaim.Status.RESERVED
                    and request.claim_token is not None
                    and existing.claim_token == request.claim_token
                ):
                    reservations.append(
                        SchedulerClaimReservation(
                            claim_id=existing.id,
                            claim_token=existing.claim_token,
                            tenant_key=request.tenant_key,
                            occurrence_key=request.occurrence_key,
                            workflow_id=request.workflow_id,
                        )
                    )
                    replayed_reservations += 1
                    already_claimed += request_count - 1
                    continue
                already_claimed += request_count
                continue
            if global_available <= 0 or tenant_available[request.tenant_key] <= 0:
                deferred_for_capacity += request_count
                continue

            claim_token = request.claim_token or uuid.uuid4()
            if existing is None:
                claim = TemporalSchedulerClaim(
                    scheduler=scheduler,
                    region=region,
                    tenant_key=request.tenant_key,
                    occurrence_hash=item.occurrence_hash,
                    occurrence_key=request.occurrence_key,
                    workflow_id=request.workflow_id,
                    claim_token=claim_token,
                    status=TemporalSchedulerClaim.Status.RESERVED,
                    lease_expires_at=lease_expires_at,
                )
                new_claims.append(claim)
            else:
                claim = existing
                claim.claim_token = claim_token
                claim.status = TemporalSchedulerClaim.Status.RESERVED
                claim.attempt_count += 1
                claim.lease_expires_at = lease_expires_at
                claim.completed_at = None
                claim.last_error = ""
                claim.updated_at = claim_time
                reused_claims.append(claim)

            reservations.append(
                SchedulerClaimReservation(
                    claim_id=claim.id,
                    claim_token=claim_token,
                    tenant_key=request.tenant_key,
                    occurrence_key=request.occurrence_key,
                    workflow_id=request.workflow_id,
                )
            )
            already_claimed += request_count - 1
            global_available -= 1
            tenant_available[request.tenant_key] -= 1
            admitted_per_tenant[request.tenant_key] += 1

        admitted_count = len(reservations) - replayed_reservations
        if admitted_count:
            global_pool.in_flight += admitted_count
            global_pool.save(update_fields=["in_flight", "updated_at"])
            touched_pools: list[TemporalSchedulerPermitPool] = []
            for tenant_key, admitted in admitted_per_tenant.items():
                pool = tenant_pools[tenant_key]
                pool.in_flight += admitted
                pool.updated_at = claim_time
                touched_pools.append(pool)
            TemporalSchedulerPermitPool.objects.bulk_update(
                touched_pools,
                ["in_flight", "updated_at"],
                batch_size=MAX_CLAIM_REQUESTS_PER_CALL,
            )
            TemporalSchedulerClaim.objects.bulk_create(new_claims)
            TemporalSchedulerClaim.objects.bulk_update(
                reused_claims,
                [
                    "claim_token",
                    "status",
                    "attempt_count",
                    "lease_expires_at",
                    "completed_at",
                    "last_error",
                    "updated_at",
                ],
            )
        # Every admission for this scheduler/region takes the same global-pool lock.
        # Publishing before releasing it preserves database update order in the gauge.
        record_scheduler_metrics_safely(lambda: metrics.set_permits_in_flight(scheduler, region, global_pool.in_flight))

    result = SchedulerAdmissionResult(
        reservations=tuple(reservations),
        already_claimed=already_claimed,
        deferred_for_capacity=deferred_for_capacity,
    )
    if admitted_count:
        record_scheduler_metrics_safely(lambda: metrics.record_admission(scheduler, region, "reserved", admitted_count))
    if result.already_claimed:
        record_scheduler_metrics_safely(
            lambda: metrics.record_admission(scheduler, region, "already_claimed", result.already_claimed)
        )
    if result.deferred_for_capacity:
        record_scheduler_metrics_safely(
            lambda: metrics.record_admission(scheduler, region, "deferred_capacity", result.deferred_for_capacity)
        )
    return result


def _validate_lease_duration(lease_duration: timedelta) -> None:
    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be greater than zero")


def confirm_scheduler_claim(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    *,
    lease_duration: timedelta,
    now: datetime | None = None,
    metrics: SchedulerMetrics = DEFAULT_SCHEDULER_METRICS,
) -> bool:
    _validate_lease_duration(lease_duration)
    transition_time = _resolve_time(now)
    with transaction.atomic():
        _set_scheduler_lock_timeout()
        claim = (
            TemporalSchedulerClaim.objects.select_for_update()
            .filter(
                id=claim_id,
                claim_token=claim_token,
                status__in=[TemporalSchedulerClaim.Status.RESERVED, TemporalSchedulerClaim.Status.CONFIRMED],
            )
            .first()
        )
        if claim is None:
            return False
        transitioned = claim.status == TemporalSchedulerClaim.Status.RESERVED
        proposed_expiry = transition_time + lease_duration
        updates: dict[str, object] = {}
        if transitioned:
            updates["status"] = TemporalSchedulerClaim.Status.CONFIRMED
        if claim.lease_expires_at is None or proposed_expiry > claim.lease_expires_at:
            updates["lease_expires_at"] = proposed_expiry
        if transition_time > claim.updated_at:
            updates["updated_at"] = transition_time
        if updates:
            TemporalSchedulerClaim.objects.filter(id=claim_id).update(**updates)
    if transitioned:
        record_scheduler_metrics_safely(lambda: _record_claim_transition_for_id(claim_id, metrics, "confirmed"))
    return True


def renew_scheduler_claim(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    *,
    lease_duration: timedelta,
    now: datetime | None = None,
    metrics: SchedulerMetrics = DEFAULT_SCHEDULER_METRICS,
) -> bool:
    _validate_lease_duration(lease_duration)
    transition_time = _resolve_time(now)
    with transaction.atomic():
        _set_scheduler_lock_timeout()
        claim = (
            TemporalSchedulerClaim.objects.select_for_update()
            .filter(
                id=claim_id,
                claim_token=claim_token,
                status=TemporalSchedulerClaim.Status.CONFIRMED,
            )
            .first()
        )
        if claim is None:
            return False
        proposed_expiry = transition_time + lease_duration
        updates: dict[str, object] = {}
        if claim.lease_expires_at is None or proposed_expiry > claim.lease_expires_at:
            updates["lease_expires_at"] = proposed_expiry
        if transition_time > claim.updated_at:
            updates["updated_at"] = transition_time
        if updates:
            TemporalSchedulerClaim.objects.filter(id=claim_id).update(**updates)
    if updates:
        record_scheduler_metrics_safely(lambda: _record_claim_transition_for_id(claim_id, metrics, "renewed"))
    return True


def defer_scheduler_claim_recovery(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    *,
    lease_duration: timedelta,
    error: str,
    expected_lease_expires_at: datetime,
    now: datetime | None = None,
    metrics: SchedulerMetrics = DEFAULT_SCHEDULER_METRICS,
) -> bool:
    """Move an uncertain expired claim behind the recovery page without releasing it."""

    _validate_lease_duration(lease_duration)
    transition_time = _resolve_time(now)
    deferred_until = transition_time + lease_duration
    updated = TemporalSchedulerClaim.objects.filter(
        id=claim_id,
        claim_token=claim_token,
        status__in=TemporalSchedulerClaim.ACTIVE_STATUSES,
        lease_expires_at=expected_lease_expires_at,
    ).update(
        lease_expires_at=deferred_until,
        last_error=error[:MAX_CLAIM_ERROR_CHARS],
        updated_at=transition_time,
    )
    if updated:
        record_scheduler_metrics_safely(lambda: _record_claim_transition_for_id(claim_id, metrics, "renewed"))
    return updated == 1


def _record_claim_transition_for_id(
    claim_id: uuid.UUID,
    metrics: SchedulerMetrics,
    transition: ClaimTransition,
) -> None:
    claim = TemporalSchedulerClaim.objects.only("scheduler", "region").get(id=claim_id)
    metrics.record_claim_transition(claim.scheduler, claim.region, transition)


def _get_locked_existing_pool(scheduler: str, region: str, tenant_key: str) -> TemporalSchedulerPermitPool:
    try:
        return TemporalSchedulerPermitPool.objects.select_for_update().get(
            scheduler=scheduler,
            region=region,
            tenant_key=tenant_key,
        )
    except TemporalSchedulerPermitPool.DoesNotExist as error:
        raise SchedulerClaimInvariantError("an active scheduler claim has no matching permit pool") from error


def _finish_scheduler_claim(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    *,
    status: TerminalClaimStatus,
    error: str,
    now: datetime | None,
    expected_lease_expires_at: datetime | None,
    allowed_active_statuses: tuple[ActiveClaimStatus, ...],
    transition: ClaimTransition,
    metrics: SchedulerMetrics,
) -> bool:
    transition_time = _resolve_time(now)
    expected_lease = _resolve_time(expected_lease_expires_at) if expected_lease_expires_at is not None else None
    snapshot = TemporalSchedulerClaim.objects.filter(id=claim_id).values("scheduler", "region", "tenant_key").first()
    if snapshot is None:
        return False

    with transaction.atomic():
        _set_scheduler_lock_timeout()
        global_pool = _get_locked_existing_pool(snapshot["scheduler"], snapshot["region"], "")
        tenant_pool = _get_locked_existing_pool(snapshot["scheduler"], snapshot["region"], snapshot["tenant_key"])
        try:
            claim = TemporalSchedulerClaim.objects.select_for_update().get(id=claim_id)
        except TemporalSchedulerClaim.DoesNotExist:
            return False
        if claim.claim_token != claim_token:
            return False
        if claim.status == status:
            return True
        if claim.status not in allowed_active_statuses:
            return False
        if expected_lease is not None and claim.lease_expires_at != expected_lease:
            return False
        if global_pool.in_flight <= 0 or tenant_pool.in_flight <= 0:
            raise SchedulerClaimInvariantError("scheduler permit counter would become negative")

        global_pool.in_flight -= 1
        tenant_pool.in_flight -= 1
        global_pool.save(update_fields=["in_flight", "updated_at"])
        tenant_pool.save(update_fields=["in_flight", "updated_at"])

        claim.status = status
        claim.lease_expires_at = None
        claim.completed_at = transition_time if status == "completed" else None
        claim.last_error = error[:MAX_CLAIM_ERROR_CHARS]
        claim.save(update_fields=["status", "lease_expires_at", "completed_at", "last_error", "updated_at"])
        permits_in_flight = global_pool.in_flight
        # Terminal transitions serialize on the same global-pool lock as admission.
        record_scheduler_metrics_safely(
            lambda: metrics.set_permits_in_flight(claim.scheduler, claim.region, permits_in_flight)
        )

    record_scheduler_metrics_safely(lambda: metrics.record_claim_transition(claim.scheduler, claim.region, transition))
    return True


def complete_scheduler_claim(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    *,
    now: datetime | None = None,
    metrics: SchedulerMetrics = DEFAULT_SCHEDULER_METRICS,
) -> bool:
    return _finish_scheduler_claim(
        claim_id,
        claim_token,
        status="completed",
        error="",
        now=now,
        expected_lease_expires_at=None,
        allowed_active_statuses=("confirmed",),
        transition="completed",
        metrics=metrics,
    )


def release_scheduler_claim(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    *,
    error: str = "",
    now: datetime | None = None,
    expected_lease_expires_at: datetime | None = None,
    metrics: SchedulerMetrics = DEFAULT_SCHEDULER_METRICS,
) -> bool:
    return _finish_scheduler_claim(
        claim_id,
        claim_token,
        status="available",
        error=error,
        now=now,
        expected_lease_expires_at=expected_lease_expires_at,
        allowed_active_statuses=("reserved", "confirmed"),
        transition="released",
        metrics=metrics,
    )


def quarantine_scheduler_claim(
    claim_id: uuid.UUID,
    claim_token: uuid.UUID,
    *,
    error: str,
    now: datetime | None = None,
    metrics: SchedulerMetrics = DEFAULT_SCHEDULER_METRICS,
) -> bool:
    return _finish_scheduler_claim(
        claim_id,
        claim_token,
        status="quarantined",
        error=error,
        now=now,
        expected_lease_expires_at=None,
        allowed_active_statuses=("reserved", "confirmed"),
        transition="quarantined",
        metrics=metrics,
    )


def list_expired_scheduler_claims(
    *,
    scheduler: str,
    region: str,
    limit: int,
    now: datetime | None = None,
) -> list[TemporalSchedulerClaim]:
    _validate_scope(scheduler, region)
    if limit <= 0 or limit > MAX_CLAIM_REQUESTS_PER_CALL:
        raise ValueError(f"limit must contain between 1 and {MAX_CLAIM_REQUESTS_PER_CALL} items")
    current_time = _resolve_time(now)
    return list(
        TemporalSchedulerClaim.objects.filter(
            scheduler=scheduler,
            region=region,
            status__in=TemporalSchedulerClaim.ACTIVE_STATUSES,
            lease_expires_at__lte=current_time,
        ).order_by("lease_expires_at", "id")[:limit]
    )


def prune_inactive_scheduler_claims(
    *,
    scheduler: str,
    region: str,
    completed_before: datetime,
    available_before: datetime,
    limit: int,
) -> int:
    """Delete a bounded batch of old, inactive claims without touching active or quarantined work.

    Callers choose explicit retention horizons. Completed claims retain durable deduplication until
    ``completed_before``; available claims remain eligible for retry until ``available_before``.
    """

    _validate_scope(scheduler, region)
    completed_cutoff = _resolve_time(completed_before)
    available_cutoff = _resolve_time(available_before)
    if limit <= 0 or limit > MAX_PRUNE_CLAIMS_PER_CALL:
        raise ValueError(f"limit must contain between 1 and {MAX_PRUNE_CLAIMS_PER_CALL} items")

    with transaction.atomic():
        _set_scheduler_lock_timeout()
        completed_candidates = list(
            TemporalSchedulerClaim.objects.select_for_update(skip_locked=True)
            .filter(
                scheduler=scheduler,
                region=region,
                status=TemporalSchedulerClaim.Status.COMPLETED,
                updated_at__lt=completed_cutoff,
            )
            .order_by("updated_at", "id")
            .values_list("id", "updated_at")[:limit]
        )
        available_candidates = list(
            TemporalSchedulerClaim.objects.select_for_update(skip_locked=True)
            .filter(
                scheduler=scheduler,
                region=region,
                status=TemporalSchedulerClaim.Status.AVAILABLE,
                updated_at__lt=available_cutoff,
            )
            .order_by("updated_at", "id")
            .values_list("id", "updated_at")[:limit]
        )
        claim_ids = [
            claim_id
            for claim_id, _updated_at in sorted(
                [*completed_candidates, *available_candidates],
                key=lambda candidate: (candidate[1], candidate[0]),
            )[:limit]
        ]
        if not claim_ids:
            return 0
        deleted, _ = TemporalSchedulerClaim.objects.filter(id__in=claim_ids).delete()
    return deleted
