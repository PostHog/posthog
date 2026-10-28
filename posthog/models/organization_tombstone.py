import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from posthog.models.organization import Organization
from posthog.models.utils import generate_slug_candidates


def tombstone_organization_record(organization_id: str) -> None:
    """Cascade-delete the Organization row, then re-insert a minimal deleted marker.

    Only the cascade removes every current and future org-scoped child row; the tombstone keeps
    id/created_at/customer_id. The name is dropped: it can contain personal data, so the tombstone
    must not retain it. bulk_create fires no signals, so the deletion workflow's billing activity
    is the real-time flag path.

    FOR UPDATE on the organization blocks concurrent FK-inserts to any child table during the
    cascade delete, like delete_team_records does for teams.
    """
    with transaction.atomic():
        # nosemgrep: hot-parent-row-select-for-update -- Organization deletion must block concurrent child inserts.
        original = (
            Organization.objects_including_soft_deleted.select_for_update()
            .filter(id=organization_id)
            .values("created_at", "customer_id", "deleted")
            .first()
        )
        if original is None or original["deleted"]:
            return
        Organization.objects_including_soft_deleted.filter(id=organization_id).delete()
        now = timezone.now()
        tombstone = Organization(
            id=organization_id,
            name="",
            deleted=True,
            deleted_at=now,
            is_active=False,
            is_not_active_reason=Organization.DeactivationReason.DELETED,
            is_pending_deletion=True,
            customer_id=original["customer_id"],
            # Dead orgs must not authorize AI processing of archived payloads queued before deletion.
            is_ai_data_processing_approved=False,
            is_ai_training_opted_in=False,
        )
        # Frees the original slug for reuse, exactly like the hard delete did. A user-created org
        # can legitimately own the first candidate, so fall back to suffixed ones on collision.
        for candidate in generate_slug_candidates(f"deleted-{uuid.UUID(str(organization_id)).hex}"):
            tombstone.slug = candidate
            try:
                with transaction.atomic():
                    Organization.objects_including_soft_deleted.bulk_create([tombstone])
                break
            except IntegrityError:
                continue
        else:
            # Rolls back the whole block, so the retried activity starts from the live row again.
            raise RuntimeError(f"Could not allocate a tombstone slug for organization {organization_id}")
        # update() bypasses auto_now_add, pinning the original creation time.
        Organization.objects_including_soft_deleted.filter(id=organization_id).update(created_at=original["created_at"])
