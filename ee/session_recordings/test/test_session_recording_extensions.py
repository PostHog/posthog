from datetime import timedelta, datetime, UTC
from secrets import token_urlsafe
from uuid import uuid4

from boto3 import resource
from botocore.config import Config
from freezegun import freeze_time

from ee.session_recordings.session_recording_extensions import (
    persist_recording,
)
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
from posthog.storage.object_storage import write, list_objects, object_storage_client
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

    def test_can_build_object_storage_paths(self) -> None:
        produce_replay_summary(
            session_id="test_can_build_different_object_storage_paths-s1",
            team_id=self.team.pk,
        )

        recording: SessionRecording = SessionRecording.objects.create(
            team=self.team,
            session_id="test_can_build_different_object_storage_paths-s1",
        )

        assert (
            recording.build_blob_lts_storage_path("2023-08-01")
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
                blob_path = f"{TEST_BUCKET}/team_id/{self.team.pk}/session_id/{session_id}/data"
                for file in ["a", "b", "c"]:
                    file_name = f"{blob_path}/{file}"
                    write(file_name, f"my content-{file}".encode())

                assert object_storage_client().list_objects(OBJECT_STORAGE_BUCKET, blob_path) == [
                    f"{blob_path}/a",
                    f"{blob_path}/b",
                    f"{blob_path}/c",
                ]

                recording: SessionRecording = SessionRecording.objects.create(team=self.team, session_id=session_id)

                assert recording.created_at == two_minutes_ago
                assert recording.storage_version is None

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

            stored_objects = list_objects(recording.build_blob_lts_storage_path("2023-08-01"))
            assert stored_objects == [
                f"{recording.build_blob_lts_storage_path('2023-08-01')}/a",
                f"{recording.build_blob_lts_storage_path('2023-08-01')}/b",
                f"{recording.build_blob_lts_storage_path('2023-08-01')}/c",
            ]
