from uuid import UUID

from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.folder_context_generation import FileSystemFolderContextGeneration


def get_context_generation_task_id(folder: FileSystem) -> UUID | None:
    """Task currently generating this folder's CONTEXT.md, or None if unset."""
    row = FileSystemFolderContextGeneration.objects.for_team(folder.team_id).filter(folder=folder).first()
    return row.task_id if row is not None else None


def set_context_generation_task_id(folder: FileSystem, *, task_id: UUID | None) -> None:
    """Set (or clear, when task_id is None) the folder's context-generation association.

    Overwrites any previous value. Idempotent per folder via the OneToOne relationship.
    """
    FileSystemFolderContextGeneration.objects.for_team(folder.team_id).update_or_create(
        folder=folder,
        defaults={"team_id": folder.team_id, "task_id": task_id},
    )


def clear_context_generation(folder: FileSystem) -> None:
    """Clear the folder's context-generation association if a row exists; no-op otherwise."""
    FileSystemFolderContextGeneration.objects.for_team(folder.team_id).filter(folder=folder).update(task_id=None)
