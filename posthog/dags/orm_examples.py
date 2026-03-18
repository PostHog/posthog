from django.db.models import Q

import dagster

from posthog.models.async_deletion import AsyncDeletion, DeletionType


@dagster.asset
def pending_deletions() -> list[AsyncDeletion]:
    """
    Asset that fetches pending async deletions from Django ORM.
    """
    pending_deletions = AsyncDeletion.objects.filter(
        Q(deletion_type=DeletionType.Person) & Q(delete_verified_at__isnull=True)
    ).all()

    return list(pending_deletions)


@dagster.asset(deps=[pending_deletions])
def process_pending_deletions(pending_deletions: list[AsyncDeletion]) -> None:
    """
    Asset that prints out pending deletions.
    """
    if not pending_deletions:
        print("No pending deletions found")  # noqa
        return

    print(f"Found {len(pending_deletions)} pending deletions:")  # noqa
    for deletion in pending_deletions:
        print(f"- Deletion ID: {deletion.id}, Type: {deletion.deletion_type}, Created at: {deletion.created_at}")  # noqa
