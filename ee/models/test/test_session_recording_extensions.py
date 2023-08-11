from datetime import timedelta, datetime, timezone
from secrets import token_urlsafe
from unittest.mock import patch
from uuid import uuid4

from boto3 import resource
from botocore.config import Config
from freezegun import freeze_time

from ee.models.session_recording_extensions import load_persisted_recording, persist_recording
from posthog.models.session_recording.session_recording import SessionRecording
from posthog.models.session_recording_playlist.session_recording_playlist import SessionRecordingPlaylist
from posthog.models.session_recording_playlist_item.session_recording_playlist_item import SessionRecordingPlaylistItem
from posthog.queries.session_recordings.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.test.test_factory import create_session_recording_events
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

    def create_snapshot(self, session_id, timestamp):
        team_id = self.team.pk

        snapshot = {
            "timestamp": timestamp.timestamp() * 1000,
            "has_full_snapshot": 1,
            "type": 2,
            "data": {"source": 0, "href": long_url},
        }

        # can't immediately switch playlists to replay table
        create_session_recording_events(
            team_id=team_id,
            distinct_id="distinct_id_1",
            timestamp=timestamp,
            session_id=session_id,
            window_id="window_1",
            snapshots=[snapshot],
            use_recording_table=True,
            use_replay_table=False,
        )

    def test_does_not_persist_too_recent_recording(self):
        recording = SessionRecording.objects.create(
            team=self.team, session_id=f"test_does_not_persist_too_recent_recording-s1-{uuid4()}"
        )
        self.create_snapshot(recording.session_id, recording.created_at)
        persist_recording(recording.session_id, recording.team_id)
        recording.refresh_from_db()

        assert not recording.object_storage_path

    def test_persists_recording_with_original_version_when_not_in_blob_storage(self):
        two_minutes_ago = (datetime.now() - timedelta(minutes=2)).replace(tzinfo=timezone.utc)
        with freeze_time(two_minutes_ago):
            recording = SessionRecording.objects.create(
                team=self.team, session_id=f"test_persists_recording-s1-{uuid4()}"
            )

            self.create_snapshot(recording.session_id, recording.created_at - timedelta(hours=48))
            self.create_snapshot(recording.session_id, recording.created_at - timedelta(hours=46))

            produce_replay_summary(
                session_id=recording.session_id,
                team_id=self.team.pk,
                first_timestamp=(recording.created_at - timedelta(hours=48)).isoformat(),
                last_timestamp=(recording.created_at - timedelta(hours=46)).isoformat(),
                distinct_id="distinct_id_1",
                first_url="https://app.posthog.com/my-url",
            )

        persist_recording(recording.session_id, recording.team_id)
        recording.refresh_from_db()

        assert (
            recording.object_storage_path
            == f"session_recordings_lts/team-{self.team.pk}/session-{recording.session_id}"
        )
        assert recording.start_time == recording.created_at - timedelta(hours=48)
        assert recording.end_time == recording.created_at - timedelta(hours=46)

        assert recording.distinct_id == "distinct_id_1"
        assert recording.duration == 7200
        assert recording.click_count == 0
        assert recording.keypress_count == 0
        assert recording.start_url == "https://app.posthog.com/my-url"

        assert load_persisted_recording(recording) == {
            "version": "2022-12-22",
            "distinct_id": "distinct_id_1",
            "snapshot_data_by_window_id": {
                "window_1": [
                    {
                        "timestamp": (recording.created_at - timedelta(hours=48)).timestamp() * 1000,
                        "has_full_snapshot": 1,
                        "type": 2,
                        "data": {"source": 0, "href": long_url},
                    },
                    {
                        "timestamp": (recording.created_at - timedelta(hours=46)).timestamp() * 1000,
                        "has_full_snapshot": 1,
                        "type": 2,
                        "data": {"source": 0, "href": long_url},
                    },
                ]
            },
        }

    def test_can_build_different_object_storage_paths(self) -> None:
        produce_replay_summary(
            session_id="test_can_build_different_object_storage_paths-s1",
            team_id=self.team.pk,
        )
        recording: SessionRecording = SessionRecording.objects.create(
            team=self.team, session_id="test_can_build_different_object_storage_paths-s1"
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
            two_minutes_ago = (datetime.now() - timedelta(minutes=2)).replace(tzinfo=timezone.utc)

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
                    write(file_name, f"my content-{file}".encode("utf-8"))

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

    @patch("ee.models.session_recording_extensions.report_team_action")
    def test_persist_tracks_correct_to_posthog(self, mock_capture):
        two_minutes_ago = (datetime.now() - timedelta(minutes=2)).replace(tzinfo=timezone.utc)

        with freeze_time(two_minutes_ago):
            playlist = SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user)
            recording = SessionRecording.objects.create(
                team=self.team, session_id=f"test_persist_tracks_correct_to_posthog-s1-{uuid4()}"
            )
            SessionRecordingPlaylistItem.objects.create(playlist=playlist, recording=recording)

            self.create_snapshot(recording.session_id, recording.created_at - timedelta(hours=48))
            self.create_snapshot(recording.session_id, recording.created_at - timedelta(hours=46))

            produce_replay_summary(
                session_id=recording.session_id,
                team_id=self.team.pk,
                first_timestamp=(recording.created_at - timedelta(hours=48)).isoformat(),
                last_timestamp=(recording.created_at - timedelta(hours=46)).isoformat(),
                distinct_id="distinct_id_1",
                first_url="https://app.posthog.com/my-url",
            )

        persist_recording(recording.session_id, recording.team_id)

        assert mock_capture.call_args_list[0][0][0] == recording.team
        assert mock_capture.call_args_list[0][0][1] == "session recording persisted"

        for x in [
            "total_time_ms",
        ]:
            assert mock_capture.call_args_list[0][0][2][x] > 0
