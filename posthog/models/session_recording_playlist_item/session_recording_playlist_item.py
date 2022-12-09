from django.db import models

from posthog.models.team import Team


class SessionRecordingPlaylistItem(models.Model):
    class Meta:
        unique_together = ("recording_id", "playlist_id", "team")

    recording: models.ForeignKey = models.ForeignKey(
        "SessionRecording", related_name="playlist_items", on_delete=models.CASCADE, null=True, to_field="session_id"
    )
    playlist: models.ForeignKey = models.ForeignKey(
        "SessionRecordingPlaylist", related_name="playlist_items", on_delete=models.CASCADE
    )
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE, null=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(null=True, blank=True)

    # DEPRECATED: Now using recording_id
    session_id: models.CharField = models.CharField(max_length=200)
