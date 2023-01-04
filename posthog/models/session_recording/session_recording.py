from datetime import datetime
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

    distinct_id: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    duration: models.IntegerField = models.IntegerField(null=True)
    start_time: models.DateTimeField = models.DateTimeField(null=True)
    end_time: models.DateTimeField = models.DateTimeField(null=True)
    click_count: models.IntegerField = models.IntegerField(null=True)
    keypress_count: models.IntegerField = models.IntegerField(null=True)
    start_url: models.CharField = models.CharField(null=True, max_length=512)

    # DYNAMIC FIELDS

    viewed: Optional[bool] = False
    matching_events: Optional[RecordingMatchingEvents] = None

    # Metadata can be loaded from Clickhouse or S3
    _metadata: Optional[RecordingMetadata] = None
    _snapshots: Optional[DecompressedRecordingData] = None

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
            self.distinct_id = metadata["distinct_id"]

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

    # S3 / Clickhouse backed fields
    @property
    def snapshot_data_by_window_id(self):
        return self._snapshots["snapshot_data_by_window_id"] if self._snapshots else None

    @property
    def can_load_more_snapshots(self):
        return self._snapshots["has_next"] if self._snapshots else False

    @property
    def segments(self):
        return self._metadata["segments"] if self._metadata else None

    @property
    def start_and_end_times_by_window_id(self):
        return self._metadata["start_and_end_times_by_window_id"] if self._metadata else None

    @property
    def storage(self):
        return "object_storage" if self.object_storage_path else "clickhouse"

    @cached_property
    def person(self) -> Optional[Person]:
        # Move this to _property so we can set it in a bulk command as well
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

    @staticmethod
    def get_or_build_from_clickhouse(team: Team, ch_recordings: List[dict]) -> "List[SessionRecording]":
        session_ids = [recording["session_id"] for recording in ch_recordings]

        recordings_by_id = {
            recording.session_id: recording
            for recording in SessionRecording.objects.filter(session_id__in=session_ids, team=team).all()
        }

        recordings = []

        for ch_recording in ch_recordings:
            recording = recordings_by_id.get(ch_recording["session_id"]) or SessionRecording(
                session_id=ch_recording["session_id"], team=team
            )

            recording.start_time = ch_recording["start_time"]
            recording.end_time = ch_recording["end_time"]
            recording.click_count = ch_recording["click_count"]
            recording.keypress_count = ch_recording["keypress_count"]
            recording.duration = ch_recording["duration"]
            recording.distinct_id = ch_recording["distinct_id"]
            recording.start_url = ch_recording["urls"][0]
            recordings.append(recording)

        return recordings

    # TODO: add metadata field to keep minimal information on this model for quick access


@receiver(models.signals.post_save, sender=SessionRecording)
def attempt_persist_recoding(sender, instance: SessionRecording, created: bool, **kwargs):
    if created:
        ee_persist_single_recording.delay(instance.session_id, instance.team_id)
