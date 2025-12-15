from io import BytesIO

from django.db import models
from django.utils import timezone

import structlog

from posthog.models.team import Team
from posthog.models.utils import UUIDModel
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)


class FeedbackAudio(UUIDModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="feedback_audio")
    feedback_id = models.CharField(max_length=255, help_text="Identifier linking this audio to a feedback submission")

    # Audio metadata
    audio_size = models.PositiveIntegerField(help_text="Size of audio file in bytes")
    content_type = models.CharField(max_length=50, help_text="MIME type of the audio file")

    # Storage location
    media_location = models.TextField(blank=True, null=True, help_text="Object storage location of the audio file")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "feedback_id"], name="unique_feedback_audio_per_team")]
        indexes = [
            models.Index(fields=["team", "created_at"]),
            models.Index(fields=["feedback_id"]),
        ]

    def __str__(self):
        return f"FeedbackAudio({self.feedback_id}, {self.content_type}, {self.audio_size} bytes)"

    def save_audio_data(self, audio_data: bytes) -> bool:
        """
        Save audio data to object storage and update the media_location field.

        Args:
            audio_data: Raw audio file bytes

        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            # Generate a unique filename
            file_extension = self._get_file_extension_from_content_type()
            filename = f"feedback_audio/{self.team_id}/{self.id}{file_extension}"

            # Save to object storage
            audio_stream = BytesIO(audio_data)
            object_storage.write(filename, audio_stream)

            # Update the media location
            self.media_location = filename
            self.save(update_fields=["media_location"])

            logger.info(
                "feedback_audio_saved",
                team_id=self.team_id,
                feedback_id=self.feedback_id,
                audio_id=str(self.id),
                file_size=len(audio_data),
                location=filename,
            )

            return True

        except Exception as e:
            logger.error(
                "feedback_audio_save_failed",
                team_id=self.team_id,
                feedback_id=self.feedback_id,
                audio_id=str(self.id),
                error=str(e),
                exc_info=True,
            )
            return False

    def get_audio_data(self) -> bytes | None:
        """
        Retrieve audio data from object storage.

        Returns:
            bytes: Audio file data, or None if not found
        """
        if not self.media_location:
            return None

        try:
            return object_storage.read_bytes(self.media_location)
        except Exception as e:
            logger.error(
                "feedback_audio_read_failed",
                team_id=self.team_id,
                feedback_id=self.feedback_id,
                audio_id=str(self.id),
                location=self.media_location,
                error=str(e),
                exc_info=True,
            )
            return None

    def _get_file_extension_from_content_type(self) -> str:
        """Get appropriate file extension based on content type."""
        content_type_mapping = {
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".mp4",
            "audio/m4a": ".m4a",
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/flac": ".flac",
        }
        return content_type_mapping.get(self.content_type, ".audio")
