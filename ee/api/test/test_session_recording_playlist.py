from freezegun import freeze_time
from rest_framework import status

from posthog.models import SessionRecordingPlaylistItem
from posthog.models.session_recording_playlist.session_recording_playlist import SessionRecordingPlaylist
from posthog.models.user import User
from posthog.test.base import APIBaseTest


class TestSessionRecordingPlaylist(APIBaseTest):
    def test_list_playlists(self):
        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
        }

    @freeze_time("2022-01-01")
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
            "created_at": "2022-01-01T00:00:00Z",
            "created_by": response.json()["created_by"],
            "deleted": False,
            "filters": {},
            "last_modified_at": "2022-01-01T00:00:00Z",
            "last_modified_by": response.json()["last_modified_by"],
            "is_static": False,
            "playlist_items": [],
        }

    @freeze_time("2022-01-01")
    def test_creates_static_playlist(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists", data={"name": "test", "is_static": True}
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json() == {
            "id": response.json()["id"],
            "short_id": response.json()["short_id"],
            "name": "test",
            "derived_name": None,
            "description": "",
            "pinned": False,
            "created_at": "2022-01-01T00:00:00Z",
            "created_by": response.json()["created_by"],
            "deleted": False,
            "filters": {},
            "last_modified_at": "2022-01-01T00:00:00Z",
            "last_modified_by": response.json()["last_modified_by"],
            "is_static": True,
            "playlist_items": [],
        }

    @freeze_time("2022-01-01")
    def test_gets_individual_playlist_by_shortid(self):
        create_response = self.client.post(f"/api/projects/{self.team.id}/session_recording_playlists")
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{create_response.json()['short_id']}"
        )

        assert response.json()["short_id"] == create_response.json()["short_id"]

    @freeze_time("2022-01-01")
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
        assert response.json()["created_at"] == "2022-01-01T00:00:00Z"
        assert response.json()["last_modified_at"] == "2022-01-02T00:00:00Z"

    @freeze_time("2022-01-01")
    def test_rejects_updates_readonly_playlist_properties(self):
        short_id = self.client.post(f"/api/projects/{self.team.id}/session_recording_playlists/").json()["short_id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
            {"short_id": "something else", "pinned": True},
        )

        assert response.json()["short_id"] == short_id
        assert response.json()["pinned"]

    @freeze_time("2022-01-01")
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
        assert results[0]["short_id"] == playlist1.short_id
        assert results[1]["short_id"] == playlist3.short_id

        results = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?user=true",
        ).json()["results"]

        assert len(results) == 2
        assert results[0]["short_id"] == playlist1.short_id
        assert results[1]["short_id"] == playlist2.short_id

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

    @freeze_time("2022-01-01")
    def test_fetch_static_playlist_items(self):
        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team, name="playlist1", created_by=self.user, is_static=True
        )
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team, name="playlist2", created_by=self.user, is_static=True
        )

        SessionRecordingPlaylistItem.objects.create(session_id="1-playlist1", playlist=playlist1)
        SessionRecordingPlaylistItem.objects.create(session_id="2-playlist1", playlist=playlist1)
        SessionRecordingPlaylistItem.objects.create(session_id="3-playlist2", playlist=playlist2)

        result = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}",
        ).json()

        assert result["short_id"] == playlist1.short_id
        assert result["playlist_items"] == [
            {
                "id": "1-playlist1",
                "created_at": "2022-01-01T00:00:00Z",
            },
            {
                "id": "2-playlist1",
                "created_at": "2022-01-01T00:00:00Z",
            },
        ]

        result = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}",
        ).json()

        assert result["short_id"] == playlist2.short_id
        assert result["playlist_items"] == [
            {
                "id": "3-playlist2",
                "created_at": "2022-01-01T00:00:00Z",
            },
        ]
