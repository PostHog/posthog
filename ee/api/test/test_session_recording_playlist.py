from datetime import datetime
from unittest import mock

from freezegun import freeze_time
from rest_framework import status

from ee.api.test.base import APILicensedTest
from posthog.models.session_recording_playlist.session_recording_playlist import SessionRecordingPlaylist
from posthog.models.user import User
from posthog.session_recordings.test.test_factory import create_session_recording_events


class TestSessionRecordingPlaylist(APILicensedTest):
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
        response = self.client.post(f"/api/projects/{self.team.id}/session_recording_playlists", data={"name": "test"})
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

        create_session_recording_events(
            team_id=self.team.id,
            distinct_id="123",
            timestamp=datetime.utcnow(),
            session_id="session1",
            window_id="1234",
        )

        create_session_recording_events(
            team_id=self.team.id,
            distinct_id="123",
            timestamp=datetime.utcnow(),
            session_id="session2",
            window_id="1234",
        )

        # Create playlist items
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/session1"
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/session2"
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/session-missing"
        )

        # Test get recordings
        result = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings"
        ).json()
        assert len(result["results"]) == 2
        assert {x["id"] for x in result["results"]} == {"session1", "session2"}
