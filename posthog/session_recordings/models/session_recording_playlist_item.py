from django.db import models


class SessionRecordingPlaylistItem(models.Model):
    recording = models.ForeignKey(
        "SessionRecording",
        related_name="playlist_items",
        on_delete=models.CASCADE,
        to_field="session_id",
        null=True,
        blank=True,
    )
    playlist = models.ForeignKey(
        "SessionRecordingPlaylist",
        related_name="playlist_items",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    # DEPRECATED: We hard delete as this is only a joiner table
    deleted = models.BooleanField(null=True, blank=True)
    # DEPRECATED: Use recording_id instead
    session_id = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        unique_together = ("recording", "playlist")
        # The unique_together above indexes (recording, playlist) leading with recording,
        # which cannot serve lookups by playlist alone. The playlist-only index is needed
        # by the list API to batch-count items across a page of playlists.
        indexes = [
            models.Index(fields=["playlist"], name="srpi_playlist_idx"),
        ]
