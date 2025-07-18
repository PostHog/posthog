from typing import Any, Literal, Optional, Union

from django.conf import settings
from django.db import models

from posthog.models.person.missing_person import MissingPerson
from posthog.models.person.person import READ_DB_FOR_PERSONS, Person
from posthog.models.signals import mutable_receiver
from posthog.models.team.team import Team
from posthog.models.utils import UUIDModel
from posthog.session_recordings.models.metadata import (
    RecordingMatchingEvents,
    RecordingMetadata,
)
from posthog.session_recordings.models.session_recording_event import (
    SessionRecordingViewed,
)
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.tasks.tasks import ee_persist_single_recording


class SessionRecording(UUIDModel):
    class Meta:
        unique_together = ("team", "session_id")

    # Note: UUIDT is the PostHog standard, but session_id's are generated with a different util in posthog-js
    # https://github.com/PostHog/posthog-js/blob/e0dc2c005cfb5dd62b7c876676bcffe1654417a7/src/utils.ts#L457-L458
    # We create recording objects with both UUIDT and a unique session_id field to remain backwards compatible.
    # All other models related to the session recording model uses this unique `session_id` to create the link.
    session_id = models.CharField(unique=True, max_length=200)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    deleted = models.BooleanField(null=True, blank=True)
    object_storage_path = models.CharField(max_length=200, null=True, blank=True)
    full_recording_v2_path = models.CharField(max_length=1000, null=True, blank=True)

    distinct_id = models.CharField(max_length=400, null=True, blank=True)

    duration = models.IntegerField(blank=True, null=True)
    active_seconds = models.IntegerField(blank=True, null=True)
    inactive_seconds = models.IntegerField(blank=True, null=True)
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)

    click_count = models.IntegerField(blank=True, null=True)
    keypress_count = models.IntegerField(blank=True, null=True)
    mouse_activity_count = models.IntegerField(blank=True, null=True)

    console_log_count = models.IntegerField(blank=True, null=True)
    console_warn_count = models.IntegerField(blank=True, null=True)
    console_error_count = models.IntegerField(blank=True, null=True)

    start_url = models.CharField(blank=True, null=True, max_length=512)

    # we can't store storage version in the stored content
    # as we might need to know the version before knowing how to load the data
    storage_version = models.CharField(blank=True, null=True, max_length=20)

    # DYNAMIC FIELDS

    viewed: Optional[bool] = False
    viewers: Optional[list[str]] = None
    _person: Optional[Person] = None
    matching_events: Optional[RecordingMatchingEvents] = None
    ongoing: Optional[bool] = None
    activity_score: Optional[float] = None

    # Metadata can be loaded from Clickhouse or S3
    _metadata: Optional[RecordingMetadata] = None

    def load_metadata(self) -> bool:
        if self._metadata:
            return True

        if self.object_storage_path:
            # Nothing todo as we have all the metadata in the model
            pass
        else:
            # Try to load from Clickhouse
            metadata = SessionReplayEvents().get_metadata(
                team_id=self.team.pk,
                session_id=self.session_id,
                recording_start_time=self.start_time,
            )

            if not metadata:
                return False

            self._metadata = metadata

            # Some fields of the metadata are persisted fully in the model
            self.distinct_id = metadata["distinct_id"]
            self.start_time = metadata["start_time"]
            self.end_time = metadata["end_time"]
            self.duration = metadata["duration"]
            self.click_count = metadata["click_count"]
            self.keypress_count = metadata["keypress_count"]
            self.set_start_url_from_urls(first_url=metadata["first_url"])
            self.mouse_activity_count = metadata["mouse_activity_count"]
            self.active_seconds = metadata["active_seconds"]
            self.inactive_seconds = metadata["duration"] - metadata["active_seconds"]
            self.console_log_count = metadata["console_log_count"]
            self.console_warn_count = metadata["console_warn_count"]
            self.console_error_count = metadata["console_error_count"]

        return True

    @property
    def storage(self):
        if self._state.adding:
            return "object_storage"

        return "object_storage_lts"

    @property
    def snapshot_source(self) -> Optional[str]:
        return self._metadata.get("snapshot_source", "web") if self._metadata else "web"

    @property
    def person(self) -> Union[Person, MissingPerson]:
        if self._person:
            return self._person

        # kludge: satisfy mypy by making distinct_id always a string.
        # if distinct_id is none we've got bigger problems
        return MissingPerson(team_id=self.team_id, distinct_id=self.distinct_id or "")

    @person.setter
    def person(self, value: Person):
        self._person = value

    def load_person(self):
        if self._person:
            return

        try:
            self.person = Person.objects.db_manager(READ_DB_FOR_PERSONS).get(
                persondistinctid__distinct_id=self.distinct_id,
                persondistinctid__team_id=self.team.pk,
                team=self.team,
            )
        except Person.DoesNotExist:
            pass

    def check_viewed_for_user(self, user: Any, save_viewed=False) -> None:
        if not save_viewed:
            self.viewed = SessionRecordingViewed.objects.filter(
                team=self.team, user=user, session_id=self.session_id
            ).exists()
        else:
            SessionRecordingViewed.objects.get_or_create(team=self.team, user=user, session_id=self.session_id)
            self.viewed = True

    def build_blob_lts_storage_path(self, version: Literal["2023-08-01"]) -> str:
        if version == "2023-08-01":
            return self.build_blob_ingestion_storage_path(settings.OBJECT_STORAGE_SESSION_RECORDING_LTS_FOLDER)
        else:
            raise NotImplementedError(f"Unknown session replay object storage version {version}")

    def build_blob_ingestion_storage_path(self, root_prefix: Optional[str] = None) -> str:
        root_prefix = root_prefix or settings.OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER
        return f"{root_prefix}/team_id/{self.team_id}/session_id/{self.session_id}/data"

    @staticmethod
    def get_or_build(session_id: str, team: Team) -> "SessionRecording":
        try:
            return SessionRecording.objects.get(session_id=session_id, team=team)
        except SessionRecording.DoesNotExist:
            return SessionRecording(session_id=session_id, team=team)

    @staticmethod
    def get_or_build_from_clickhouse(team: Team, ch_recordings: list[dict]) -> "list[SessionRecording]":
        session_ids = sorted([recording["session_id"] for recording in ch_recordings])

        recordings_by_id = {
            recording.session_id: recording
            for recording in SessionRecording.objects.filter(session_id__in=session_ids, team=team).all()
        }

        recordings = []

        for ch_recording in ch_recordings:
            recording = recordings_by_id.get(ch_recording["session_id"]) or SessionRecording(
                session_id=ch_recording["session_id"], team=team
            )

            recording.distinct_id = ch_recording["distinct_id"]
            recording.start_time = ch_recording["start_time"]
            recording.end_time = ch_recording["end_time"]
            recording.duration = ch_recording["duration"]
            recording.active_seconds = ch_recording.get("active_seconds", 0)
            recording.inactive_seconds = ch_recording.get("inactive_seconds", 0)
            recording.click_count = ch_recording["click_count"]
            recording.keypress_count = ch_recording["keypress_count"]
            recording.mouse_activity_count = ch_recording.get("mouse_activity_count", 0)
            recording.console_log_count = ch_recording.get("console_log_count", None)
            recording.console_warn_count = ch_recording.get("console_warn_count", None)
            recording.console_error_count = ch_recording.get("console_error_count", None)
            recording.set_start_url_from_urls(ch_recording.get("urls", None), ch_recording.get("first_url", None))
            recording.ongoing = bool(ch_recording.get("ongoing", False))
            recording.activity_score = ch_recording.get("activity_score", None)

            recordings.append(recording)

        return recordings

    def set_start_url_from_urls(self, urls: Optional[list[str]] = None, first_url: Optional[str] = None):
        if first_url:
            self.start_url = first_url[:512]
            return

        url = urls[0] if urls else None
        self.start_url = url.split("?")[0][:512] if url else None


@mutable_receiver(models.signals.post_save, sender=SessionRecording)
def attempt_persist_recording(sender, instance: SessionRecording, created: bool, **kwargs):
    if created:
        ee_persist_single_recording.delay(instance.session_id, instance.team_id)
