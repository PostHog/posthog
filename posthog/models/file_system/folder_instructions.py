from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models.file_system.file_system import FileSystem
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class FileSystemFolderInstructions(TeamScopedRootMixin, UUIDModel):
    """
    A versioned markdown instructions blob attached to a single FileSystem folder.

    Each edit publishes a new row (incrementing `version`, flipping the previous `is_latest`
    off), mirroring the skills store's versioning so history is preserved and auditable.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    folder = models.ForeignKey(FileSystem, on_delete=models.CASCADE, related_name="instruction_versions")

    # The markdown instructions describing the contents of the folder.
    content = models.TextField()

    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True)
    deleted = models.BooleanField(default=False)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["folder", "version"],
                condition=Q(deleted=False),
                name="unique_folder_instructions_version",
            ),
            models.UniqueConstraint(
                fields=["folder"],
                condition=Q(deleted=False, is_latest=True),
                name="unique_folder_instructions_latest",
            ),
        ]
