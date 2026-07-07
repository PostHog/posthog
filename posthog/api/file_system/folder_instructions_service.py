from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from posthog.api.file_system.folder_context_generation_service import clear_context_generation
from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.folder_instructions import FileSystemFolderInstructions
from posthog.models.user import User

# Generous cap on the markdown blob; folder instructions are descriptions, not documents.
FOLDER_INSTRUCTIONS_MAX_BYTES = 100_000
MAX_FOLDER_INSTRUCTIONS_VERSION = 2000


class FolderInstructionsNotFoundError(Exception):
    pass


@dataclass
class FolderInstructionsVersionConflictError(Exception):
    current_version: int


@dataclass
class FolderInstructionsVersionLimitError(Exception):
    max_version: int


def get_folder_instructions_versions(folder: FileSystem) -> QuerySet[FileSystemFolderInstructions]:
    """All non-deleted versions for a folder, newest first."""
    return (
        FileSystemFolderInstructions.objects.filter(folder=folder, deleted=False)
        .select_related("created_by")
        .order_by("-version", "-created_at", "-id")
    )


def get_latest_folder_instructions(folder: FileSystem) -> FileSystemFolderInstructions | None:
    return get_folder_instructions_versions(folder).filter(is_latest=True).first()


def publish_folder_instructions(
    folder: FileSystem,
    *,
    content: str,
    user: User,
    base_version: int | None = None,
) -> FileSystemFolderInstructions:
    """Create the first version, or publish a new version superseding the current latest.

    `base_version`, when provided, guards against lost updates: if the current latest version no
    longer matches it, a `FolderInstructionsVersionConflictError` is raised.
    """
    with transaction.atomic():
        current_latest = (
            FileSystemFolderInstructions.objects.select_for_update()
            .filter(folder=folder, deleted=False, is_latest=True)
            .order_by("-version", "-created_at", "-id")
            .first()
        )

        if current_latest is None:
            if base_version is not None and base_version != 0:
                raise FolderInstructionsVersionConflictError(current_version=0)
            published = FileSystemFolderInstructions.objects.create(
                team=folder.team,
                folder=folder,
                content=content,
                version=1,
                is_latest=True,
                created_by=user,
            )
        else:
            if base_version is not None and base_version != current_latest.version:
                raise FolderInstructionsVersionConflictError(current_version=current_latest.version)
            if current_latest.version >= MAX_FOLDER_INSTRUCTIONS_VERSION:
                raise FolderInstructionsVersionLimitError(max_version=MAX_FOLDER_INSTRUCTIONS_VERSION)

            FileSystemFolderInstructions.objects.filter(pk=current_latest.pk).update(is_latest=False)
            published = FileSystemFolderInstructions.objects.create(
                team=folder.team,
                folder=folder,
                content=content,
                version=current_latest.version + 1,
                is_latest=True,
                created_by=user,
            )

        # Publishing produced a result, so drop the in-progress generation marker for this folder.
        clear_context_generation(folder)
        return published


def ensure_blank_folder_instructions(
    folder: FileSystem,
    *,
    user: User | None,
) -> FileSystemFolderInstructions | None:
    """Create a blank version-1 instructions row for a folder if it has none.

    Idempotent: returns None when instructions already exist (so every folder ends up with an
    instruction set, even an empty one, without ever clobbering existing content).
    """
    if FileSystemFolderInstructions.objects.filter(folder=folder, deleted=False).exists():
        return None
    try:
        return FileSystemFolderInstructions.objects.create(
            team=folder.team,
            folder=folder,
            content="",
            version=1,
            is_latest=True,
            created_by=user,
        )
    except IntegrityError:
        # A concurrent create won the race; the folder now has instructions.
        return None


def delete_folder_instructions(folder: FileSystem) -> int:
    """Soft-delete every version for a folder. Returns the number of versions affected."""
    with transaction.atomic():
        count = (
            FileSystemFolderInstructions.objects.select_for_update()
            .filter(folder=folder, deleted=False)
            .update(deleted=True, is_latest=False)
        )
        # No instructions remain, so the folder can't have a generation in progress.
        clear_context_generation(folder)
    return count
