from django.db import models
from django.utils import timezone

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

    # DEPRECATED
    is_static = models.BooleanField(default=False)

    # Changing these fields materially alters the Playlist, so these count for the "last_modified_*" fields
    MATERIAL_PLAYLIST_FIELDS = {"name", "description", "filters"}

    class Meta:
        unique_together = ("team", "short_id")
