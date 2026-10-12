import os
from uuid import UUID

from django.db import transaction

from products.authz.backend.logic.sync_state import mark_pending


def synchronization_enabled() -> bool:
    return os.getenv("OPENFGA_SYNC_ENABLED", "").lower() in {"1", "true"}


def schedule_organization_sync(organization_id: UUID, *, using: str = "default") -> None:
    if not synchronization_enabled():
        return

    def enqueue() -> None:
        # Defer task imports off the receiver registration path.
        from products.authz.backend.tasks.tasks import synchronize_organization  # noqa: PLC0415

        mark_pending(organization_id)
        synchronize_organization.delay(str(organization_id))

    transaction.on_commit(enqueue, using=using)
