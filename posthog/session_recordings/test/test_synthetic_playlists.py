from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status

from posthog.models import Comment, SessionRecordingPlaylist
from posthog.models.exported_asset import ExportedAsset
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed

try:
    from ee.models.session_summaries import SingleSessionSummary

    HAS_EE = True
except ImportError:
    HAS_EE = False


class TestSyntheticPlaylists(APIBaseTest):
    def _get_playlists_response(self, query_params: str = "") -> dict:
        url = f"/api/projects/{self.team.id}/session_recording_playlists{query_params}"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def _count_synthetic_playlists(self, results: list[dict]) -> int:
        return len([p for p in results if p["short_id"].startswith("synthetic-")])

    def _get_synthetic_playlists(self, query_params: str = "") -> list[str]:
        response_data = self._get_playlists_response(query_params)
        return [p["short_id"] for p in response_data["results"] if p["short_id"].startswith("synthetic-")]

    def _get_synthetic_playlist(self, short_id: str) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_list_includes_synthetic_playlists(self) -> None:
        synthetic_short_ids = self._get_synthetic_playlists()

        expected = [
            "synthetic-watch-history",
            "synthetic-commented",
            "synthetic-shared",
            "synthetic-exported",
            "synthetic-expiring",
        ]
        if HAS_EE:
            expected.append("synthetic-summarised")

        assert sorted(synthetic_short_ids) == sorted(expected)

    def test_retrieve_synthetic_playlist(self) -> None:
        playlist = self._get_synthetic_playlist("synthetic-watch-history")

        assert playlist["short_id"] == "synthetic-watch-history"
        assert playlist["name"] == "Watch history"
        assert playlist["type"] == "collection"
        assert playlist["created_by"] is None
        assert playlist["last_modified_by"] is None
        assert playlist["created_at"] is None
        assert playlist["last_modified_at"] is None

    def test_synthetic_playlist_watch_history_content(self) -> None:
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="watched-session-1")
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="watched-session-2")

        playlist = self._get_synthetic_playlist("synthetic-watch-history")

        assert playlist["recordings_counts"]["collection"]["count"] == 2

    def test_synthetic_playlist_pagination(self) -> None:
        from posthog.session_recordings.synthetic_playlists import WatchedPlaylistSource

        for i in range(5):
            SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id=f"watched-session-{i}")

        source = WatchedPlaylistSource()

        page1 = source.get_session_ids(self.team, self.user, limit=2, offset=0)
        page2 = source.get_session_ids(self.team, self.user, limit=2, offset=2)
        page3 = source.get_session_ids(self.team, self.user, limit=2, offset=4)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

        assert set(page1).isdisjoint(set(page2))
        assert set(page1).isdisjoint(set(page3))
        assert set(page2).isdisjoint(set(page3))

        all_pages = page1 + page2 + page3
        assert len(set(all_pages)) == 5

    def test_synthetic_playlist_commented_content(self) -> None:
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            content="Great recording!",
            scope="Replay",
            item_id="commented-session-1",
        )
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            content="Another comment",
            scope="Replay",
            item_id="commented-session-2",
        )

        playlist = self._get_synthetic_playlist("synthetic-commented")

        assert playlist["recordings_counts"]["collection"]["count"] == 2

    def test_synthetic_playlist_shared_content(self) -> None:
        from posthog.models import SessionRecording

        recording1 = SessionRecording.objects.create(team=self.team, session_id="shared-session-1")
        recording2 = SessionRecording.objects.create(team=self.team, session_id="shared-session-2")

        SharingConfiguration.objects.create(
            team=self.team, recording=recording1, enabled=True, access_token="test-token-1"
        )
        SharingConfiguration.objects.create(
            team=self.team, recording=recording2, enabled=True, access_token="test-token-2"
        )

        playlist = self._get_synthetic_playlist("synthetic-shared")

        assert playlist["recordings_counts"]["collection"]["count"] == 2

    def test_synthetic_playlist_exported_content(self) -> None:
        ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.GIF,
            export_context={"session_recording_id": "exported-session-1"},
            created_by=self.user,
        )
        ExportedAsset.objects.create(
            team=self.team,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"session_recording_id": "exported-session-2"},
            created_by=self.user,
        )

        playlist = self._get_synthetic_playlist("synthetic-exported")

        assert playlist["recordings_counts"]["collection"]["count"] == 2

    @parameterized.expand(
        [
            ["type_filters", "type=filters", []],
            ["user", "user=true", []],
            ["pinned", "pinned=true", []],
            ["created_by", "created_by={user_id}", []],
            ["?search=watch", "search=watch", ["synthetic-watch-history"]],
        ]
    )
    def test_filter_excludes_synthetic_playlists(
        self, _name: str, query_template: str, expected_results: list[str]
    ) -> None:
        query_params = f"?{query_template.format(user_id=self.user.id)}"
        synthetic_short_ids = self._get_synthetic_playlists(query_params)

        assert synthetic_short_ids == expected_results

    def test_cannot_update_synthetic_playlist(self) -> None:
        playlist = self._get_synthetic_playlist("synthetic-watch-history")
        assert playlist["short_id"] == "synthetic-watch-history"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/synthetic-watch-history",
            {"name": "Modified name", "description": "Modified description"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_delete_synthetic_playlist(self) -> None:
        playlist = self._get_synthetic_playlist("synthetic-watch-history")
        assert playlist["short_id"] == "synthetic-watch-history"

        response = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/synthetic-watch-history"
        )

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_synthetic_playlist_summarised_content(self) -> None:
        if not HAS_EE:
            # Skip test if EE is not available
            return

        SingleSessionSummary.objects.create(
            team=self.team,
            session_id="summarised-session-1",
            summary={"content": "User completed checkout flow"},
            created_by=self.user,
        )
        SingleSessionSummary.objects.create(
            team=self.team,
            session_id="summarised-session-2",
            summary={"content": "User encountered error on login"},
            created_by=self.user,
        )

        playlist = self._get_synthetic_playlist("synthetic-summarised")

        assert playlist["recordings_counts"]["collection"]["count"] == 2

    def test_pagination_includes_synthetics_only_on_first_page(self) -> None:
        for i in range(25):
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name=f"DB Playlist {i}",
                created_by=self.user,
                type="collection",
            )

        expected_synthetic_count = 6 if HAS_EE else 5

        page1_data = self._get_playlists_response("?limit=20")
        page1_synthetic_count = self._count_synthetic_playlists(page1_data["results"])

        assert page1_synthetic_count == expected_synthetic_count
        assert page1_data["count"] == 25 + expected_synthetic_count

        page2_data = self._get_playlists_response("?limit=20&offset=20")
        page2_synthetic_count = self._count_synthetic_playlists(page2_data["results"])

        assert page2_synthetic_count == 0
        assert page2_data["count"] == 25 + expected_synthetic_count

    @parameterized.expand(
        [
            ("descending", "-last_modified_at", True),
            ("ascending", "last_modified_at", False),
        ]
    )
    def test_synthetic_playlists_sort_position(self, _name: str, order_param: str, synthetics_first: bool) -> None:
        base_time = now()

        playlist_old = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Old Playlist",
            created_by=self.user,
            type="collection",
            last_modified_at=base_time - timedelta(days=10),
        )
        playlist_middle = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Middle Playlist",
            created_by=self.user,
            type="collection",
            last_modified_at=base_time - timedelta(days=5),
        )
        playlist_new = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="New Playlist",
            created_by=self.user,
            type="collection",
            last_modified_at=base_time,
        )

        expected_synthetic_count = 6 if HAS_EE else 5

        response_data = self._get_playlists_response(f"?order={order_param}")
        results = response_data["results"]

        if synthetics_first:
            for i in range(expected_synthetic_count):
                assert results[i]["short_id"].startswith("synthetic-")
            assert results[expected_synthetic_count]["short_id"] == playlist_new.short_id
            assert results[expected_synthetic_count + 1]["short_id"] == playlist_middle.short_id
            assert results[expected_synthetic_count + 2]["short_id"] == playlist_old.short_id
        else:
            assert results[0]["short_id"] == playlist_old.short_id
            assert results[1]["short_id"] == playlist_middle.short_id
            assert results[2]["short_id"] == playlist_new.short_id
            for i in range(3, 3 + expected_synthetic_count):
                assert results[i]["short_id"].startswith("synthetic-")
