from django.db import models


class SessionRecordingPlaylistItem(models.Model):
    session_id: models.CharField = models.CharField(max_length=200)
    playlist: models.ForeignKey = models.ForeignKey(
        "SessionRecordingPlaylist", related_name="playlist_items", on_delete=models.CASCADE
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(null=True, blank=True)

    class Meta:
        unique_together = ("session_id", "playlist_id")
