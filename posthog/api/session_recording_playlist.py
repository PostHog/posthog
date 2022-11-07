from rest_framework import serializers

from posthog.models import SessionRecordingPlaylist


class SessionRecordingPlaylistSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionRecordingPlaylist
        fields = [
            "id",
            "short_id",
            "name",
            "description",
            "team",
            "pinned",
            "created_at",
            "created_by",
            "deleted",
            "filters",
            "last_modified_at",
        ]
