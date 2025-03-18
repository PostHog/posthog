from django.db import models
from django.utils import timezone
from django.db.models.indexes import Index
from posthog.utils import generate_short_id


class SessionRecordingPlaylist(models.Model):
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=400, null=True, blank=True)
    derived_name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    pinned = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    filters = models.JSONField(default=dict)
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
