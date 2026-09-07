import uuid
from collections.abc import Iterable

from django.db import connection, transaction
from django.db.models import QuerySet

from posthog.models.entity_dependencies.models import EntityDependency
from posthog.models.entity_dependencies.types import Reference, SyncResult
from posthog.models.scoping.manager import resolve_effective_team_id


def sync_dependencies(*, team_id: int, source_type: str, source_id: str, references: Iterable[Reference]) -> SyncResult:
    """Make the stored rows for one source equal to `references`.

    Idempotent: running it twice with the same input changes nothing the second time. Runs in
    the caller's transaction when there is one, so the rows roll back together with the source
    write. The savepoint also keeps a failed sync from poisoning the caller's transaction.
    """
    # Rows are project-scoped like RootTeamMixin models. bulk_create skips the mixin's save()
    # rewrite, so the canonical team is resolved here to keep writes symmetric with for_team reads.
    team_id = resolve_effective_team_id(team_id)
    desired = set(references)
    with transaction.atomic():
        _lock_source(source_type, source_id)
        scoped = EntityDependency.objects.for_team(team_id, canonical=True)
        stored = _stored_references(scoped, source_type, source_id)

        to_add = desired - stored.keys()
        to_remove = [row_id for reference, row_id in stored.items() if reference not in desired]

        if to_add:
            scoped.bulk_create(
                [
                    EntityDependency(
                        team_id=team_id,
                        source_type=source_type,
                        source_id=source_id,
                        target_type=reference.target_type,
                        target_id=reference.target_id,
                        role=reference.role,
                        path=reference.path,
                    )
                    for reference in to_add
                ],
                ignore_conflicts=True,
            )
        if to_remove:
            scoped.filter(id__in=to_remove).delete()

    return SyncResult(added=len(to_add), removed=len(to_remove))


def plan_sync(*, team_id: int, source_type: str, source_id: str, references: Iterable[Reference]) -> SyncResult:
    """Report what `sync_dependencies` would change for this input, without writing anything."""
    team_id = resolve_effective_team_id(team_id)
    desired = set(references)
    scoped = EntityDependency.objects.for_team(team_id, canonical=True)
    stored = _stored_references(scoped, source_type, source_id)
    return SyncResult(added=len(desired - stored.keys()), removed=len(stored.keys() - desired))


def remove_dependencies(*, team_id: int, source_type: str, source_id: str) -> int:
    with transaction.atomic():
        _lock_source(source_type, source_id)
        deleted, _ = (
            EntityDependency.objects.for_team(team_id).filter(source_type=source_type, source_id=source_id).delete()
        )
    return deleted


def _lock_source(source_type: str, source_id: str) -> None:
    # PostHog has no ATOMIC_REQUESTS, so two concurrent saves of the same source are not
    # serialized by a row lock. The transaction-scoped advisory lock makes the read-diff-write
    # above safe against a concurrent sync of the same source.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"entity_dependency:{source_type}:{source_id}"])


def _stored_references(
    scoped: QuerySet[EntityDependency], source_type: str, source_id: str
) -> dict[Reference, uuid.UUID]:
    return {_to_reference(row): row.id for row in scoped.filter(source_type=source_type, source_id=source_id)}


def _to_reference(row: EntityDependency) -> Reference:
    return Reference(target_type=row.target_type, target_id=row.target_id, role=row.role, path=row.path)
