from typing import Any, List, Optional

from django.db import models
from django.dispatch import receiver

from posthog import settings
from posthog.celery import ee_persist_single_recording
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.person.person import Person
from posthog.models.session_recording.metadata import DecompressedRecordingData, RecordingMetadata
from posthog.models.session_recording_event.session_recording_event import SessionRecordingViewed
from posthog.models.team.team import Team
from posthog.models.utils import UUIDModel


class SessionRecording(UUIDModel):

    # Note: UUIDT is the PostHog standard, but session_id's are generated with a different util in posthog-js
    # https://github.com/PostHog/posthog-js/blob/e0dc2c005cfb5dd62b7c876676bcffe1654417a7/src/utils.ts#L457-L458
    # We create recording objects with both UUIDT and a unique session_id field to remain backwards compatible.
    # All other models related to the session recording model uses this unique `session_id` to create the link.
    session_id: models.CharField = models.CharField(unique=True, max_length=200)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    object_storage_path: models.CharField = models.CharField(max_length=200, null=True, blank=True)

    # DYNAMIC FIELDS

    viewed: Optional[bool] = False

    # Metadata can be loaded from Clickhouse or S3
    _metadata: Optional[RecordingMetadata] = None
    _snapshots: Optional[DecompressedRecordingData] = None

    def load_metadata(self) -> None:
        from posthog.queries.session_recordings.session_recording_events import SessionRecordingEvents

        if not self.object_storage_path:
            # Try to load from Clickhouse
            metadata = SessionRecordingEvents(
                team=self.team,
                session_recording_id=self.session_id,
                recording_start_time=None,  # TODO Add this as an otpimisation
            ).get_metadata()

            if not metadata:
                return

        self._metadata = metadata

    def load_snapshots(self, limit=20, offset=0) -> None:
        from posthog.queries.session_recordings.session_recording_events import SessionRecordingEvents

        if not self.object_storage_path:
            snapshots = SessionRecordingEvents(
                team=self.team,
                session_recording_id=self.session_id,
                recording_start_time=None,  # TODO Add this as an otpimisation
            ).get_snapshots(limit, offset)

            self._snapshots = snapshots

    @property
    def snapshot_data_by_window_id(self):
        return self._snapshots["snapshot_data_by_window_id"] if self._snapshots else None

    @property
    def distinct_id(self):
        return self._metadata["distinct_id"] if self._metadata else None

    @property
    def segments(self):
        return self._metadata["segments"] if self._metadata else None

    @property
    def start_and_end_times_by_window_id(self):
        return self._metadata["start_and_end_times_by_window_id"] if self._metadata else None

    @property
    def duration(self):
        return None

    @property
    def start_time(self):
        return None

    @property
    def end_time(self):
        return None

    @property
    def click_count(self):
        return None

    @property
    def keypress_count(self):
        return None

    @property
    def urls(self):
        return None

    @property
    def matching_events(self):
        return None

    @cached_property
    def person(self) -> Optional[Person]:
        if not self.distinct_id:
            return None

        try:
            return Person.objects.get(
                persondistinctid__distinct_id=self.distinct_id,
                persondistinctid__team_id=self.team,
                team=self.team,
            )
        except Person.DoesNotExist:
            return None

    def check_viewed_for_user(self, user: Any) -> None:
        self.viewed = SessionRecordingViewed.objects.filter(
            team=self.team, user=user, session_id=self.session_id
        ).exists()

    def build_object_storage_path(self) -> str:
        path_parts: List[str] = [
            settings.OBJECT_STORAGE_SESSION_RECORDING_FOLDER,
            f"team-{self.team_id}",
            f"session-{self.session_id}",
        ]

        return f'/{"/".join(path_parts)}'

    @staticmethod
    def get_or_build(session_id: str, team: Team) -> "SessionRecording":
        try:
            return SessionRecording.objects.get(session_id=session_id, team=team)
        except SessionRecording.DoesNotExist:
            return SessionRecording(session_id=session_id, team=team)

    # TODO: add metadata field to keep minimal information on this model for quick access


@receiver(models.signals.post_save, sender=SessionRecording)
def attempt_persist_recoding(sender, instance: SessionRecording, created: bool, **kwargs):
    if created:
        ee_persist_single_recording.delay(instance.session_id, instance.team_id)
