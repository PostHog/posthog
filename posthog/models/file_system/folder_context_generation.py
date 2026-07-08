from django.db import models
from django.utils import timezone

from posthog.models.file_system.file_system import FileSystem
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class FileSystemFolderContextGeneration(TeamScopedRootMixin, UUIDModel):
    """
    Tracks which Task is currently generating a folder's CONTEXT.md (folder instructions).

    Project-shared, per-(team, folder) marker so any user in the project sees the in-progress state.
    Anchored on the folder rather than the instructions because the first generation runs before any
    instructions exist. `task_id` references a Task in the same team; it is a plain UUID rather than a
    FK because Task lives in the `tasks` product app and a `posthog -> tasks` FK would invert the app
    dependency. Cleared (set to null) automatically when a new instructions version is published.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    folder = models.OneToOneField(FileSystem, on_delete=models.CASCADE, related_name="context_generation")

    task_id = models.UUIDField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
