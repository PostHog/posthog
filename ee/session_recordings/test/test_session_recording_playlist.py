from datetime import datetime, timedelta, UTC
from unittest import mock
from unittest.mock import MagicMock, patch
from uuid import uuid4

from boto3 import resource
from botocore.config import Config
from django.test import override_settings
from freezegun import freeze_time
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.api.test.fixtures.available_product_features import AVAILABLE_PRODUCT_FEATURES
from posthog.models import SessionRecording, SessionRecordingPlaylistItem
from posthog.models.user import User
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
)
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

TEST_BUCKET = "test_storage_bucket-ee.TestSessionRecordingPlaylist"


@override_settings(
    OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER=TEST_BUCKET,
    OBJECT_STORAGE_SESSION_RECORDING_LTS_FOLDER=f"{TEST_BUCKET}_lts",
)
class TestSessionRecordingPlaylist(APILicensedTest):
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

    def test_list_playlists(self):
        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }

    def test_creates_playlist(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists",
            data={"name": "test"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {
            "id": response.json()["id"],
            "short_id": response.json()["short_id"],
            "name": "test",
            "derived_name": None,
            "description": "",
            "pinned": False,
            "created_at": mock.ANY,
            "created_by": response.json()["created_by"],
            "deleted": False,
            "filters": {},
            "last_modified_at": mock.ANY,
            "last_modified_by": response.json()["last_modified_by"],
        }

    def test_creates_too_many_playlists(self):
        limit = 0
        self.organization.available_product_features = AVAILABLE_PRODUCT_FEATURES
        self.organization.save()
        for feature in AVAILABLE_PRODUCT_FEATURES:
            if "key" in feature and feature["key"] == "recordings_playlists":
                limit = int(feature["limit"])
        for _ in range(limit):
            response = self.client.post(
                f"/api/projects/{self.team.id}/session_recording_playlists",
                data={"name": "test"},
            )
            assert response.status_code == status.HTTP_201_CREATED
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists",
            data={"name": "test"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_gets_individual_playlist_by_shortid(self):
        create_response = self.client.post(f"/api/projects/{self.team.id}/session_recording_playlists")
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{create_response.json()['short_id']}"
        )

        assert response.json()["short_id"] == create_response.json()["short_id"]

    def test_updates_playlist(self):
        short_id = self.client.post(f"/api/projects/{self.team.id}/session_recording_playlists/").json()["short_id"]

        with freeze_time("2022-01-02"):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
                {
                    "name": "changed name",
                    "description": "changed description",
                    "filters": {"events": [{"id": "test"}]},
                    "pinned": True,
                },
            )

        assert response.json()["short_id"] == short_id
        assert response.json()["name"] == "changed name"
        assert response.json()["description"] == "changed description"
        assert response.json()["filters"] == {"events": [{"id": "test"}]}
        assert response.json()["created_at"] == mock.ANY
        assert response.json()["last_modified_at"] == "2022-01-02T00:00:00Z"

    def test_rejects_updates_to_readonly_playlist_properties(self):
        short_id = self.client.post(f"/api/projects/{self.team.id}/session_recording_playlists/").json()["short_id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
            {"short_id": "something else", "pinned": True},
        )

        assert response.json()["short_id"] == short_id
        assert response.json()["pinned"]

    def test_filters_based_on_params(self):
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        playlist1 = SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user)
        playlist2 = SessionRecordingPlaylist.objects.create(team=self.team, pinned=True, created_by=self.user)
        playlist3 = SessionRecordingPlaylist.objects.create(team=self.team, name="my playlist", created_by=other_user)

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?search=my",
        ).json()["results"]

        assert len(results) == 1
        assert results[0]["short_id"] == playlist3.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?search=playlist",
        ).json()["results"]

        assert len(results) == 2
        assert results[0]["short_id"] == playlist3.short_id
        assert results[1]["short_id"] == playlist1.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?user=true",
        ).json()["results"]

        assert len(results) == 2
        assert results[0]["short_id"] == playlist2.short_id
        assert results[1]["short_id"] == playlist1.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?pinned=true",
        ).json()["results"]

        assert len(results) == 1
        assert results[0]["short_id"] == playlist2.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?created_by={other_user.id}",
        ).json()["results"]

        assert len(results) == 1
        assert results[0]["short_id"] == playlist3.short_id

    @patch("ee.session_recordings.session_recording_extensions.object_storage.copy_objects")
    def test_get_pinned_recordings_for_playlist(self, mock_copy_objects: MagicMock) -> None:
        mock_copy_objects.return_value = 2

        playlist = SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user)

        session_one = f"test_fetch_playlist_recordings-session1-{uuid4()}"
        session_two = f"test_fetch_playlist_recordings-session2-{uuid4()}"
        three_days_ago = (datetime.now() - timedelta(days=3)).replace(tzinfo=UTC)

        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_one,
            distinct_id="123",
            first_timestamp=three_days_ago,
            last_timestamp=three_days_ago,
        )

        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_two,
            distinct_id="123",
            first_timestamp=three_days_ago,
            last_timestamp=three_days_ago,
        )

        # Create playlist items
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{session_one}"
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{session_two}"
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/session-missing"
        )

        # Test get recordings
        result = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings"
        ).json()
        assert len(result["results"]) == 2
        assert {x["id"] for x in result["results"]} == {session_one, session_two}

    @patch("ee.session_recordings.session_recording_extensions.object_storage.list_objects")
    @patch("ee.session_recordings.session_recording_extensions.object_storage.copy_objects")
    def test_fetch_playlist_recordings(self, mock_copy_objects: MagicMock, mock_list_objects: MagicMock) -> None:
        # all sessions have been blob ingested and had data to copy into the LTS storage location
        mock_copy_objects.return_value = 1

        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist1",
            created_by=self.user,
        )
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist2",
            created_by=self.user,
        )

        session_one = f"test_fetch_playlist_recordings-session1-{uuid4()}"
        session_two = f"test_fetch_playlist_recordings-session2-{uuid4()}"
        three_days_ago = (datetime.now() - timedelta(days=3)).replace(tzinfo=UTC)

        for session_id in [session_one, session_two]:
            produce_replay_summary(
                team_id=self.team.id,
                session_id=session_id,
                distinct_id="123",
                first_timestamp=three_days_ago,
                last_timestamp=three_days_ago,
            )

        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{session_one}",
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{session_two}",
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{session_one}",
        )

        result = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings",
        ).json()

        assert len(result["results"]) == 2
        assert result["results"][0]["id"] == session_one
        assert result["results"][1]["id"] == session_two

        # Test get recordings
        result = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings",
        ).json()

        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == session_one

    def test_add_remove_static_playlist_items(self):
        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist1",
            created_by=self.user,
        )
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist2",
            created_by=self.user,
        )

        recording1_session_id = "1"
        recording2_session_id = "2"

        # Add recording 1 to playlist 1
        result = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording1_session_id}",
        ).json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist1.id, session_id=recording1_session_id
        )
        assert playlist_item is not None

        # Add recording 2 to playlist 1
        result = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist1.id, session_id=recording2_session_id
        )
        assert playlist_item is not None

        # Add recording 2 to playlist 2
        result = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist2.id, session_id=recording2_session_id
        )
        assert playlist_item is not None

        session_recording_obj_1 = SessionRecording.get_or_build(team=self.team, session_id=recording1_session_id)
        assert session_recording_obj_1

        session_recording_obj_2 = SessionRecording.get_or_build(team=self.team, session_id=recording2_session_id)
        assert session_recording_obj_2

        # Delete playlist items
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording1_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist1.id, session_id=recording1_session_id
            ).count()
            == 0
        )
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist1.id, session_id=recording2_session_id
            ).count()
            == 0
        )
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist2.id, session_id=recording1_session_id
            ).count()
            == 0
        )
