from typing import Any, Dict, List, Optional

from django.db import models
from django.dispatch import receiver

from posthog import settings
from posthog.celery import ee_persist_single_recording
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.person.person import Person
from posthog.models.session_recording.metadata import (
    DecompressedRecordingData,
    RecordingMatchingEvents,
    RecordingMetadata,
)
from posthog.models.session_recording_event.session_recording_event import SessionRecordingViewed
from posthog.models.team.team import Team
from posthog.models.utils import UUIDModel


class SessionRecording(UUIDModel):
    class Meta:
        unique_together = ("team", "session_id")

    # Note: UUIDT is the PostHog standard, but session_id's are generated with a different util in posthog-js
    # https://github.com/PostHog/posthog-js/blob/e0dc2c005cfb5dd62b7c876676bcffe1654417a7/src/utils.ts#L457-L458
    # We create recording objects with both UUIDT and a unique session_id field to remain backwards compatible.
    # All other models related to the session recording model uses this unique `session_id` to create the link.
    session_id: models.CharField = models.CharField(unique=True, max_length=200)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    object_storage_path: models.CharField = models.CharField(max_length=200, null=True, blank=True)

    # Metadata persisted on postgres
    metadata: models.JSONField = models.JSONField(default=dict)

    # DYNAMIC FIELDS

    viewed: Optional[bool] = False
    matching_events: Optional[RecordingMatchingEvents] = None

    # Metadata can be loaded from Clickhouse or S3
    _metadata: Optional[RecordingMetadata] = None
    _snapshots: Optional[DecompressedRecordingData] = None

    def save_persisted_metadata(self, metadata: Dict[str, str]) -> None:
        # TODO: call this method on only persisted session recordings on list call
        if self.metadata:
            return

        self.metadata = metadata
        self.save()

    def load_metadata(self) -> None:
        from posthog.queries.session_recordings.session_recording_events import SessionRecordingEvents

        if self._metadata:
            return

        if self.object_storage_path:
            self.load_object_data()
        else:
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

        if self._snapshots:
            return

        if self.object_storage_path:
            self.load_object_data()
        else:
            snapshots = SessionRecordingEvents(
                team=self.team,
                session_recording_id=self.session_id,
                recording_start_time=None,  # TODO Add this as an optimisation
            ).get_snapshots(limit, offset)

            self._snapshots = snapshots

    def load_object_data(self) -> None:
        try:
            from ee.models.session_recording_extensions import load_persisted_recording
        except ImportError:
            pass

        data = load_persisted_recording(self)

        if not data:
            return

        self._metadata = {
            "distinct_id": data["distinct_id"],
            "start_and_end_times_by_window_id": data["start_and_end_times_by_window_id"],
            "segments": data["segments"],
        }

        self._snapshots = {
            "has_next": False,
            "snapshot_data_by_window_id": data["snapshot_data_by_window_id"],
        }

    @property
    def snapshot_data_by_window_id(self):
        return self._snapshots["snapshot_data_by_window_id"] if self._snapshots else None

    @property
    def can_load_more_snapshots(self):
        return self._snapshots["has_next"] if self._snapshots else False

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
        return self.metadata["duration"]

    @property
    def start_time(self):
        return self.metadata["start_time"]

    @property
    def end_time(self):
        return self.metadata["end_time"]

    @property
    def click_count(self):
        return self.metadata["click_count"]

    @property
    def keypress_count(self):
        return self.metadata["keypress_count"]

    @property
    def urls(self):
        return self.metadata["urls"]

    @property
    def matching_events(self):
        return self.matching_events

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
