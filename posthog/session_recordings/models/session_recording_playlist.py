from typing import TYPE_CHECKING

from django.db import models
from django.db.models import QuerySet
from django.db.models.indexes import Index
from django.utils import timezone

from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.utils import generate_short_id

if TYPE_CHECKING:
    from posthog.models.team import Team


class SessionRecordingPlaylist(FileSystemSyncMixin, models.Model):
    class PlaylistType(models.TextChoices):
        COLLECTION = "collection", "Collection"
        FILTERS = "filters", "Filters"

    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=400, null=True, blank=True)
    derived_name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    pinned = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    filters = models.JSONField(default=dict)
    type = models.CharField(max_length=50, choices=PlaylistType.choices, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_playlists",
    )
    # playlists are periodically counted,
    # we want to avoid processing the same playlists over and over
    # so we store the last time we counted a playlist on success
    # (even though counts are in Redis)
    # so we can sort by least frequently counted
    last_counted_at = models.DateTimeField(null=True, blank=True)

    # DEPRECATED
    is_static = models.BooleanField(default=False)

    # Changing these fields materially alters the Playlist, so these count for the "last_modified_*" fields
    MATERIAL_PLAYLIST_FIELDS = {"name", "description", "filters"}

    class Meta:
        unique_together = ("team", "short_id")
        indexes = [
            Index(fields=["deleted", "last_counted_at"], name="deleted_n_last_count_idx"),
            Index(fields=["deleted", "-last_modified_at"], name="deleted_n_last_mod_desc_idx"),
        ]

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["SessionRecordingPlaylist"]:
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="session_recording_playlist", ref_field="short_id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Replay playlists"),
            type="session_recording_playlist",  # sync with APIScopeObject in scopes.py
            ref=str(self.short_id),
            name=self.name or self.derived_name or "Untitled",
            href=f"/replay/playlists/{self.short_id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=self.deleted,
        )


class SessionRecordingPlaylistViewed(models.Model):
    viewed_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    playlist = models.ForeignKey("SessionRecordingPlaylist", on_delete=models.CASCADE)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("user", "playlist", "viewed_at")
        indexes = [
            models.Index(fields=["playlist"]),
            models.Index(fields=["playlist", "viewed_at"]),
        ]
