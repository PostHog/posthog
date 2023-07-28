from datetime import datetime
from typing import List
from unittest import mock
from uuid import uuid4

from freezegun import freeze_time
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.api.test.fixtures.available_product_features import AVAILABLE_PRODUCT_FEATURES
from posthog.models import SessionRecording, SessionRecordingPlaylistItem, Team
from posthog.models.session_recording_playlist.session_recording_playlist import SessionRecordingPlaylist
from posthog.models.user import User
from posthog.queries.session_recordings.test.session_replay_sql import produce_replay_summary


class TestSessionRecordingPlaylist(APILicensedTest):
    def setUp(self):
        super().setUp()

        # a race I couldn't figure out meant that the test_fetch_playlist_recordings
        # would sometimes fail when run with the other tests 🤷
        self.team = Team.objects.create(organization=self.organization)

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
        playlist_name = str(uuid4())
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists", data={"name": playlist_name}
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {
            "id": response.json()["id"],
            "short_id": response.json()["short_id"],
            "name": playlist_name,
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
        for feature in AVAILABLE_PRODUCT_FEATURES:
            if "key" in feature and feature["key"] == "recordings_playlists":
                limit = int(feature["limit"])
        for _ in range(limit):
            response = self.client.post(
                f"/api/projects/{self.team.id}/session_recording_playlists", data={"name": "test"}
            )
            assert response.status_code == status.HTTP_201_CREATED
        response = self.client.post(f"/api/projects/{self.team.id}/session_recording_playlists", data={"name": "test"})
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

    def test_get_pinned_recordings_for_playlist(self):
        playlist = SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user)

        session_one = f"test_get_pinned_recordings_for_playlist-session1-{uuid4()}"
        session_two = f"test_get_pinned_recordings_for_playlist-session2-{uuid4()}"

        produce_replay_summary(
            session_id=session_one,
            team_id=self.team.pk,
            first_timestamp=(datetime.utcnow()).isoformat(),
            last_timestamp=(datetime.utcnow()).isoformat(),
            distinct_id="123",
        )

        produce_replay_summary(
            session_id=session_two,
            team_id=self.team.pk,
            first_timestamp=(datetime.utcnow()).isoformat(),
            last_timestamp=(datetime.utcnow()).isoformat(),
            distinct_id="123",
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
        assert {x["pinned_count"] for x in result["results"]} == {1, 1}

    def test_fetch_playlist_recordings(self):
        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test_fetch_playlist_recordings-playlist1",
            created_by=self.user,
        )
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test_fetch_playlist_recordings-playlist2",
            created_by=self.user,
        )

        session_one = f"test_fetch_playlist_recordings-session-one-{uuid4()}"
        session_two = f"test_fetch_playlist_recordings-session-two-{uuid4()}"

        for id in [session_one, session_two]:
            produce_replay_summary(
                session_id=id,
                team_id=self.team.pk,
                first_timestamp=(datetime.utcnow()).isoformat(),
                last_timestamp=(datetime.utcnow()).isoformat(),
                distinct_id="123",
            )

        add_one_response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{session_one}",
        )
        assert add_one_response.status_code == 200
        assert add_one_response.json() == {"success": True}
        self._assert_playlist_session_ids(playlist1.short_id, expected=[session_one])

        add_two_response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{session_two}",
        )
        assert add_two_response.status_code == 200
        self._assert_playlist_session_ids(playlist1.short_id, expected=[session_one, session_two])

        add_one_to_playlist_two_response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{session_one}",
        )
        assert add_one_to_playlist_two_response.status_code == 200

        # adding to playlist 2 should not affect playlist 1
        self._assert_playlist_session_ids(playlist1.short_id, expected=[session_one, session_two])
        self._assert_playlist_session_ids(playlist2.short_id, expected=[session_one])

    def _assert_playlist_session_ids(self, playlist_short_id: str, expected: List[str]) -> None:
        playlist_response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist_short_id}/recordings",
        )
        assert playlist_response.status_code == 200
        assert [r["id"] for r in playlist_response.json()["results"]] == expected

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
        assert session_recording_obj_1.pinned_count == 1

        session_recording_obj_2 = SessionRecording.get_or_build(team=self.team, session_id=recording2_session_id)
        assert session_recording_obj_2
        assert session_recording_obj_2.pinned_count == 2

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
