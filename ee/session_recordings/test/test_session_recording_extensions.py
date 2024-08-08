import gzip
from datetime import timedelta, datetime, UTC
from secrets import token_urlsafe
from unittest.mock import patch, MagicMock
from uuid import uuid4

from boto3 import resource
from botocore.config import Config
from freezegun import freeze_time

from ee.session_recordings.session_recording_extensions import (
    load_persisted_recording,
    persist_recording,
    save_recording_with_new_content,
)
from posthog.models.signals import mute_selected_signals
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.settings import (
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    OBJECT_STORAGE_BUCKET,
)
from posthog.storage.object_storage import write, list_objects
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

long_url = f"https://app.posthog.com/my-url?token={token_urlsafe(600)}"


TEST_BUCKET = "test_storage_bucket-TestSessionRecordingExtensions"


class TestSessionRecordingExtensions(ClickhouseTestMixin, APIBaseTest):
    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

    def test_does_not_persist_too_recent_recording(self):
        recording = SessionRecording.objects.create(
            team=self.team,
            session_id=f"test_does_not_persist_too_recent_recording-s1-{uuid4()}",
        )

        produce_replay_summary(
            team_id=self.team.pk,
            session_id=recording.session_id,
            distinct_id="distinct_id_1",
            first_timestamp=recording.created_at,
            last_timestamp=recording.created_at,
        )
        persist_recording(recording.session_id, recording.team_id)
        recording.refresh_from_db()

        assert not recording.object_storage_path

    def test_can_build_different_object_storage_paths(self) -> None:
        produce_replay_summary(
            session_id="test_can_build_different_object_storage_paths-s1",
            team_id=self.team.pk,
        )
        recording: SessionRecording = SessionRecording.objects.create(
            team=self.team,
            session_id="test_can_build_different_object_storage_paths-s1",
        )
        assert (
            recording.build_object_storage_path("2022-12-22")
            == f"session_recordings_lts/team-{self.team.pk}/session-test_can_build_different_object_storage_paths-s1"
        )
        assert (
            recording.build_object_storage_path("2023-08-01")
            == f"session_recordings_lts/team_id/{self.team.pk}/session_id/test_can_build_different_object_storage_paths-s1/data"
        )

    def test_persists_recording_from_blob_ingested_storage(self):
        with self.settings(OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER=TEST_BUCKET):
            two_minutes_ago = (datetime.now() - timedelta(minutes=2)).replace(tzinfo=UTC)

            with freeze_time(two_minutes_ago):
                session_id = f"test_persists_recording_from_blob_ingested_storage-s1-{uuid4()}"

                produce_replay_summary(
                    session_id=session_id,
                    team_id=self.team.pk,
                    first_timestamp=(two_minutes_ago - timedelta(hours=48)).isoformat(),
                    last_timestamp=(two_minutes_ago - timedelta(hours=46)).isoformat(),
                    distinct_id="distinct_id_1",
                    first_url="https://app.posthog.com/my-url",
                )

                # this recording already has several files stored from Mr. Blobby
                # these need to be written before creating the recording object
                for file in ["a", "b", "c"]:
                    blob_path = f"{TEST_BUCKET}/team_id/{self.team.pk}/session_id/{session_id}/data"
                    file_name = f"{blob_path}/{file}"
                    write(file_name, f"my content-{file}".encode())

                recording: SessionRecording = SessionRecording.objects.create(team=self.team, session_id=session_id)

                assert recording.created_at == two_minutes_ago

            persist_recording(recording.session_id, recording.team_id)
            recording.refresh_from_db()

            assert (
                recording.object_storage_path
                == f"session_recordings_lts/team_id/{self.team.pk}/session_id/{recording.session_id}/data"
            )
            assert recording.start_time == recording.created_at - timedelta(hours=48)
            assert recording.end_time == recording.created_at - timedelta(hours=46)

            assert recording.storage_version == "2023-08-01"
            assert recording.distinct_id == "distinct_id_1"
            assert recording.duration == 7200
            assert recording.click_count == 0
            assert recording.keypress_count == 0
            assert recording.start_url == "https://app.posthog.com/my-url"

            # recordings which were blob ingested can not be loaded with this mechanism
            assert load_persisted_recording(recording) is None

            stored_objects = list_objects(recording.build_object_storage_path("2023-08-01"))
            assert stored_objects == [
                f"{recording.build_object_storage_path('2023-08-01')}/a",
                f"{recording.build_object_storage_path('2023-08-01')}/b",
                f"{recording.build_object_storage_path('2023-08-01')}/c",
            ]

    @patch("ee.session_recordings.session_recording_extensions.object_storage.write")
    def test_can_save_content_to_new_location(self, mock_write: MagicMock):
        # mute selected signals so the post create signal does not try to persist the recording
        with self.settings(OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER=TEST_BUCKET), mute_selected_signals():
            session_id = f"{uuid4()}"

            recording = SessionRecording.objects.create(
                team=self.team,
                session_id=session_id,
                start_time=datetime.fromtimestamp(12345),
                end_time=datetime.fromtimestamp(12346),
                object_storage_path="some_starting_value",
                # None, but that would trigger the persistence behavior, and we don't want that
                storage_version="None",
            )

            new_key = save_recording_with_new_content(recording, "the new content")

            recording.refresh_from_db()

            expected_path = f"session_recordings_lts/team_id/{self.team.pk}/session_id/{recording.session_id}/data"
            assert new_key == f"{expected_path}/12345000-12346000"

            assert recording.object_storage_path == expected_path
            assert recording.storage_version == "2023-08-01"

            mock_write.assert_called_with(
                f"{expected_path}/12345000-12346000",
                gzip.compress(b"the new content"),
                extras={
                    "ContentEncoding": "gzip",
                    "ContentType": "application/json",
                },
            )
