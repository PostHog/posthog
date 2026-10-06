import json
import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS, connections, router, transaction
from django.db.models import Q
from django.utils import timezone

from products.customer_analytics.backend.facade.membership_deletion_contracts import (
    MembershipDeletionCursor,
    MembershipDeletionDetails,
    MembershipDeletionIdentityPage,
    MembershipDeletionIdentityRow,
    MembershipDeletionKind,
    MembershipDeletionPage,
    MembershipDeletionReference,
    MembershipIdentity,
)
from products.customer_analytics.backend.models.membership_deletion import (
    MembershipDeletionIdentity,
    MembershipDeletionReceipt,
    MembershipDeletionTeam,
)

if TYPE_CHECKING:
    from posthog.models.person.util import PersonTombstone


MAX_PAGE_SIZE = 250


def register_membership_deletion_team(team_id: int) -> None:
    """Call before the team's first membership write; registration survives Team deletion."""
    MembershipDeletionTeam.objects.for_team(team_id).get_or_create(team_id=team_id)


def has_registered_membership_team(team_id: int) -> bool:
    return MembershipDeletionTeam.objects.for_team(team_id).exists()


def prepare_membership_deletion(
    team_id: int,
    kind: MembershipDeletionKind,
    source_key: str,
    person_uuid: UUID | None = None,
) -> UUID:
    kind = MembershipDeletionKind(kind)
    if not source_key or len(source_key) > 255:
        raise ValueError("Deletion source key must contain between 1 and 255 characters")
    if (kind == MembershipDeletionKind.PERSON) != (person_uuid is not None):
        raise ValueError("Only person deletion requires a person UUID")
    if not has_registered_membership_team(team_id):
        raise ValueError("Membership deletion team is not registered")
    receipt, _ = MembershipDeletionReceipt.objects.for_team(team_id).get_or_create(
        team_id=team_id, kind=kind.value, source_key=source_key, person_uuid=person_uuid
    )
    return receipt.id


def _get_receipt(team_id: int, receipt_id: UUID, *, lock: bool = False) -> MembershipDeletionReceipt:
    receipts = MembershipDeletionReceipt.objects.for_team(team_id)
    if lock:
        receipts = receipts.select_for_update()
    try:
        return receipts.get(id=receipt_id)
    except MembershipDeletionReceipt.DoesNotExist:
        raise LookupError("Membership deletion receipt not found") from None


def record_person_membership_deletion(team_id: int, source_key: str, tombstone: "PersonTombstone") -> UUID:
    """Accept only the committed tombstone, not a pre-delete identity snapshot."""
    identities: dict[str, int] = {}
    for identity in tombstone.distinct_ids:
        if len(identity.id) > 400:
            raise ValueError("Membership identity exceeds 400 characters")
        if identity.id in identities and identities[identity.id] != identity.version:
            raise ValueError("Tombstone contains conflicting identity versions")
        identities[identity.id] = identity.version
    digest = hashlib.sha256(json.dumps(sorted(identities.items()), ensure_ascii=True).encode()).hexdigest()
    with transaction.atomic():
        receipt_id = prepare_membership_deletion(team_id, MembershipDeletionKind.PERSON, source_key, tombstone.uuid)
        receipt = _get_receipt(team_id, receipt_id, lock=True)
        if receipt.person_version is not None:
            if receipt.person_version != tombstone.version or receipt.identity_digest != digest:
                raise ValueError("Deletion source already has a different tombstone")
            return receipt_id
        MembershipDeletionIdentity.objects.for_team(team_id).bulk_create(
            [
                MembershipDeletionIdentity(
                    team_id=team_id, receipt_id=receipt_id, distinct_id=distinct_id, version=version
                )
                for distinct_id, version in sorted(identities.items())
            ],
            batch_size=1000,
        )
        receipt.person_version = tombstone.version
        receipt.identity_digest = digest
        receipt.confirmed_at = timezone.now()
        receipt.save(update_fields=["person_version", "identity_digest", "confirmed_at"])
        return receipt_id


def confirm_membership_deletion(team_id: int, receipt_id: UUID) -> None:
    with transaction.atomic():
        receipt = _get_receipt(team_id, receipt_id, lock=True)
        if receipt.confirmed_at is not None:
            return
        if receipt.kind == MembershipDeletionKind.PERSON:
            raise ValueError("Person deletion requires a committed tombstone")
        receipt.confirmed_at = timezone.now()
        receipt.save(update_fields=["confirmed_at"])


def get_membership_deletion(team_id: int, receipt_id: UUID) -> MembershipDeletionDetails:
    receipt = _get_receipt(team_id, receipt_id)
    return MembershipDeletionDetails(
        id=receipt.id,
        team_id=receipt.team_id,
        kind=MembershipDeletionKind(receipt.kind),
        source_key=receipt.source_key,
        person_uuid=receipt.person_uuid,
        person_version=receipt.person_version,
        created_at=receipt.created_at,
        confirmed_at=receipt.confirmed_at,
        completed_at=receipt.completed_at,
        confirmed=receipt.confirmed_at is not None,
        completed=receipt.completed_at is not None,
    )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError("Page size must be between 1 and 250")


def list_membership_deletion_identities(
    team_id: int, receipt_id: UUID, after_id: int = 0, limit: int = 250
) -> MembershipDeletionIdentityPage:
    _validate_limit(limit)
    _get_receipt(team_id, receipt_id)
    rows = list(
        MembershipDeletionIdentity.objects.for_team(team_id)
        .filter(receipt_id=receipt_id, id__gt=after_id)
        .order_by("id")[: limit + 1]
    )
    return MembershipDeletionIdentityPage(
        identities=tuple(
            MembershipDeletionIdentityRow(
                id=row.id, identity=MembershipIdentity(distinct_id=row.distinct_id, version=row.version)
            )
            for row in rows[:limit]
        ),
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


def complete_membership_deletion(team_id: int, receipt_id: UUID) -> None:
    with transaction.atomic():
        receipt = _get_receipt(team_id, receipt_id, lock=True)
        if receipt.confirmed_at is None:
            raise ValueError("Membership deletion is not confirmed")
        if receipt.completed_at is not None:
            return
        MembershipDeletionIdentity.objects.for_team(team_id).filter(receipt_id=receipt_id).delete()
        receipt.completed_at = timezone.now()
        receipt.dispatch_claimed_at = None
        receipt.next_attempt_at = None
        receipt.save(update_fields=["completed_at", "dispatch_claimed_at", "next_attempt_at"])


def _list_pending_receipts(
    *, confirmed: bool, after: MembershipDeletionCursor | None, limit: int
) -> MembershipDeletionPage:
    _validate_limit(limit)
    # Recovery discovery must reach receipts for all teams, including deleted environments.
    receipts = MembershipDeletionReceipt.objects.unscoped().filter(
        confirmed_at__isnull=not confirmed, completed_at__isnull=True
    )
    if confirmed:
        receipts = receipts.filter(dispatch_claimed_at__isnull=True).filter(
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=timezone.now())
        )
    if after is not None:
        receipts = receipts.filter(Q(created_at__gt=after.created_at) | Q(created_at=after.created_at, id__gt=after.id))
    rows = list(receipts.order_by("created_at", "id")[: limit + 1])
    return MembershipDeletionPage(
        receipts=tuple(
            MembershipDeletionReference(id=row.id, team_id=row.team_id, kind=MembershipDeletionKind(row.kind))
            for row in rows[:limit]
        ),
        next_cursor=MembershipDeletionCursor(created_at=rows[limit - 1].created_at, id=rows[limit - 1].id)
        if len(rows) > limit
        else None,
    )


def list_pending_membership_deletions(
    after: MembershipDeletionCursor | None = None, limit: int = 250
) -> MembershipDeletionPage:
    return _list_pending_receipts(confirmed=True, after=after, limit=limit)


def list_pending_preparations(
    after: MembershipDeletionCursor | None = None, limit: int = 250
) -> MembershipDeletionPage:
    return _list_pending_receipts(confirmed=False, after=after, limit=limit)


def claim_membership_deletion(team_id: int, receipt_id: UUID, *, max_running: int) -> bool:
    alias = router.db_for_write(MembershipDeletionReceipt) or DEFAULT_DB_ALIAS
    with transaction.atomic(using=alias):
        connection = connections[alias]
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                    ["customer_analytics:membership_deletion_dispatch"],
                )
                lock = cursor.fetchone()
                if not lock or not lock[0]:
                    return False
        receipt = _get_receipt(team_id, receipt_id, lock=True)
        if receipt.completed_at is not None or receipt.confirmed_at is None:
            return False
        if receipt.dispatch_claimed_at is not None:
            return True
        if receipt.next_attempt_at is not None and receipt.next_attempt_at > timezone.now():
            return False
        running = (
            MembershipDeletionReceipt.objects.unscoped()
            .filter(confirmed_at__isnull=False, completed_at__isnull=True, dispatch_claimed_at__isnull=False)
            .count()
        )
        if running >= max_running:
            return False
        receipt.dispatch_claimed_at = timezone.now()
        receipt.save(update_fields=["dispatch_claimed_at"])
        return True


def list_claimed_membership_deletions(limit: int = 250) -> tuple[MembershipDeletionReference, ...]:
    _validate_limit(limit)
    return tuple(
        MembershipDeletionReference(id=row.id, team_id=row.team_id, kind=MembershipDeletionKind(row.kind))
        for row in MembershipDeletionReceipt.objects.unscoped()
        .filter(completed_at__isnull=True, dispatch_claimed_at__isnull=False)
        .order_by("dispatch_claimed_at", "id")[:limit]
    )


def release_membership_deletion_claim(
    team_id: int, receipt_id: UUID, *, retry_after: timedelta = timedelta(minutes=15)
) -> None:
    MembershipDeletionReceipt.objects.for_team(team_id).filter(id=receipt_id, completed_at__isnull=True).update(
        dispatch_claimed_at=None, next_attempt_at=timezone.now() + retry_after
    )
