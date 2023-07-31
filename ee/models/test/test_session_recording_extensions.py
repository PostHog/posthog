from datetime import timedelta, datetime
from secrets import token_urlsafe
from unittest.mock import patch

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
from posthog.storage.object_storage import write
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

        create_session_recording_events(
            team_id=team_id,
            distinct_id="distinct_id_1",
            timestamp=timestamp,
            session_id=session_id,
            window_id="window_1",
            snapshots=[snapshot],
        )

    def test_does_not_persist_too_recent_recording(self):
        recording = SessionRecording.objects.create(team=self.team, session_id="s1")
        self.create_snapshot(recording.session_id, recording.created_at)
        persist_recording(recording.session_id, recording.team_id)
        recording.refresh_from_db()

        assert not recording.object_storage_path

    def test_persists_recording(self):
        with freeze_time("2022-01-01T12:00:00Z"):
            recording = SessionRecording.objects.create(team=self.team, session_id="s1")

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

        assert recording.object_storage_path == f"session_recordings_lts/team-{self.team.pk}/session-s1"
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
                        "timestamp": 1640865600000.0,
                        "has_full_snapshot": 1,
                        "type": 2,
                        "data": {"source": 0, "href": long_url},
                    },
                    {
                        "timestamp": 1640872800000.0,
                        "has_full_snapshot": 1,
                        "type": 2,
                        "data": {"source": 0, "href": long_url},
                    },
                ]
            },
        }

    def test_persists_recording_from_blob_ingested_storage(self):
        with self.settings(OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER=TEST_BUCKET):
            # datetime 2 minutes ago
            two_minutes_ago = datetime.now() - timedelta(minutes=2)

            with freeze_time(two_minutes_ago):
                recording: SessionRecording = SessionRecording.objects.create(team=self.team, session_id="s1")

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

                # this recording already has several files stored from Mr. Blobby
                for file in ["a", "b", "c"]:
                    file_name = recording.build_blob_ingestion_storage_path()
                    write(file_name, f"my content-{file}".encode("utf-8"))

            persist_recording(recording.session_id, recording.team_id)
            recording.refresh_from_db()

            assert recording.object_storage_path == f"session_recordings_lts/team-{self.team.pk}/session-s1"
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
                "wat": "wat",
            }

    @patch("ee.models.session_recording_extensions.report_team_action")
    def test_persist_tracks_correct_to_posthog(self, mock_capture):
        with freeze_time("2022-01-01T12:00:00Z"):
            playlist = SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user)
            recording = SessionRecording.objects.create(team=self.team, session_id="s1")
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
            "metadata_load_time_ms",
            "snapshots_load_time_ms",
            "content_size_in_bytes",
            "compressed_size_in_bytes",
        ]:
            assert mock_capture.call_args_list[0][0][2][x] > 0
