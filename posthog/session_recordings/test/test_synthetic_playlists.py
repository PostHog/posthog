from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events

from django.conf import settings
from django.core.cache import cache
from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status

from posthog.models import Comment, SessionRecording, SessionRecordingPlaylist
from posthog.models.event.sql import EVENTS_JSON_DATA_TABLE
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.utils import uuid7
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.synthetic_playlists import ExpiringPlaylistSource, FrustrationSignalsPlaylistSource

from products.exports.backend.models.exported_asset import ExportedAsset


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
            "synthetic-frustrated",
        ]

        assert sorted(synthetic_short_ids) == sorted(expected)

    def _produce_recording(self, session_id: str, retention_period_days: int) -> None:
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            first_timestamp=now() - timedelta(hours=1),
            retention_period_days=retention_period_days,
            ensure_analytics_event_in_session=False,
        )

    def test_expiring_playlist_caches_and_shares_one_scan(self) -> None:
        cache.clear()
        expiring_soon, expiring_later, expiring_after_first_scan = (str(uuid7()) for _ in range(3))
        self._produce_recording(expiring_soon, retention_period_days=5)
        self._produce_recording(expiring_later, retention_period_days=30)

        source = ExpiringPlaylistSource()

        count = source.count_session_ids(self.team, self.user)
        self._produce_recording(expiring_after_first_scan, retention_period_days=5)
        session_ids = source.get_session_ids(self.team, self.user)
        # a second list load within the cache TTL must not re-scan
        recount = source.count_session_ids(self.team, self.user)

        assert expiring_soon in session_ids
        assert expiring_later not in session_ids
        # count + get_session_ids + recount share a single cached scan
        assert expiring_after_first_scan not in session_ids
        assert recount == count == len(session_ids)

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

    def test_list_counts_each_session_once_including_numeric_export_ids(self) -> None:
        other_user = self._create_user("other@posthog.com")
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="viewed-1")
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="viewed-2")
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="123")
        SessionRecordingViewed.objects.create(team=self.team, user=other_user, session_id="viewed-by-other")
        for session_id in ("viewed-1", "viewed-1", "viewed-by-other"):
            Comment.objects.create(team=self.team, created_by=self.user, scope="Replay", item_id=session_id)
        SharingConfiguration.objects.create(
            team=self.team,
            recording=SessionRecording.objects.create(team=self.team, session_id="viewed-2"),
            enabled=True,
            access_token="shared-token",
        )
        for export_session_id in ("viewed-1", "viewed-1", "unviewed", 123):
            ExportedAsset.objects.create(
                team=self.team,
                export_format=ExportedAsset.ExportFormat.GIF,
                export_context={"session_recording_id": export_session_id},
                created_by=self.user,
            )
        cache.set(
            ExpiringPlaylistSource._get_cache_key(self.team.pk),
            ["viewed-2", "unviewed"],
            ExpiringPlaylistSource.CACHE_TTL,
        )
        cache.set(
            FrustrationSignalsPlaylistSource._get_cache_key(self.team.pk),
            [],
            FrustrationSignalsPlaylistSource.CACHE_TTL,
        )

        results = self._get_playlists_response()["results"]

        counts = {
            playlist["short_id"]: (
                playlist["recordings_counts"]["collection"]["count"],
                playlist["recordings_counts"]["collection"]["watched_count"],
            )
            for playlist in results
        }
        assert counts == {
            "synthetic-watch-history": (3, 3),
            "synthetic-commented": (2, 1),
            "synthetic-shared": (1, 1),
            "synthetic-exported": (3, 2),
            "synthetic-expiring": (2, 1),
            "synthetic-frustrated": (None, 0),
        }

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

    def test_cannot_add_recordings_to_synthetic_playlist(self) -> None:
        base = f"/api/projects/{self.team.id}/session_recording_playlists/synthetic-watch-history/recordings"

        single = self.client.post(f"{base}/session-1")
        assert single.status_code == status.HTTP_400_BAD_REQUEST

        bulk = self.client.post(f"{base}/bulk_add", {"session_recording_ids": ["session-1"]})
        assert bulk.status_code == status.HTTP_400_BAD_REQUEST

        assert SessionRecordingPlaylist.objects.count() == 0

    def test_pagination_includes_synthetics_only_on_first_page(self) -> None:
        for i in range(25):
            SessionRecordingPlaylist.objects.create(
                team=self.team,
                name=f"DB Playlist {i}",
                created_by=self.user,
                type="collection",
            )

        expected_synthetic_count = 6

        page1_data = self._get_playlists_response("?limit=20")
        assert len(page1_data["results"]) == 20
        assert page1_data["count"] == 25 + expected_synthetic_count

        page2_data = self._get_playlists_response("?limit=20&offset=20")
        page2_synthetic_count = self._count_synthetic_playlists(page2_data["results"])

        assert page2_synthetic_count == 0
        assert page2_data["count"] == 25 + expected_synthetic_count

    def test_pagination_limit_constrains_combined_results(self) -> None:
        expected_synthetic_count = 6

        # With no DB playlists, requesting limit=3 should return at most 3
        # synthetic playlists, not all of them.
        data = self._get_playlists_response("?limit=3")
        assert len(data["results"]) == 3
        assert data["count"] == expected_synthetic_count

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

        expected_synthetic_count = 6

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


class TestFrustrationSignalsSyntheticPlaylist(APIBaseTest):
    """Tests for the frustration signals synthetic playlist"""

    def setUp(self):
        super().setUp()
        from posthog.clickhouse.client import sync_execute

        sync_execute("TRUNCATE TABLE sharded_events")
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            sync_execute(f"TRUNCATE TABLE {EVENTS_JSON_DATA_TABLE}")

    def _get_playlists_response(self, query_params: str = "") -> dict:
        url = f"/api/projects/{self.team.id}/session_recording_playlists{query_params}"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def _get_synthetic_playlist(self, short_id: str) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_frustrated_playlist_appears_in_list(self) -> None:
        response_data = self._get_playlists_response()
        synthetic_short_ids = [
            p["short_id"] for p in response_data["results"] if p["short_id"].startswith("synthetic-")
        ]
        assert "synthetic-frustrated" in synthetic_short_ids

    def test_frustrated_playlist_retrieve(self) -> None:
        playlist = self._get_synthetic_playlist("synthetic-frustrated")
        assert playlist["short_id"] == "synthetic-frustrated"
        assert playlist["name"] == "Frustration signals"
        assert playlist["type"] == "collection"
        assert playlist["is_synthetic"] is True
        assert playlist["created_by"] is None

    def test_frustrated_sessions_detected(self) -> None:
        cache.clear()

        session_id = str(uuid7())
        for _ in range(2):
            _create_event(
                distinct_id="user",
                event="$rageclick",
                properties={"$session_id": session_id},
                team=self.team,
                timestamp=datetime.now() - timedelta(days=1),
            )
        flush_persons_and_events()

        source = FrustrationSignalsPlaylistSource()
        session_ids = source.get_session_ids(self.team, self.user)
        assert session_id in session_ids

    def test_frustrated_sessions_ordered_by_score(self) -> None:
        cache.clear()

        # session_a: 2 rage clicks = score 6
        session_a = str(uuid7())
        for _ in range(2):
            _create_event(
                distinct_id="user",
                event="$rageclick",
                properties={"$session_id": session_a},
                team=self.team,
                timestamp=datetime.now() - timedelta(days=1),
            )

        # session_b: 2 rage clicks + 1 exception = score 8
        session_b = str(uuid7())
        for _ in range(2):
            _create_event(
                distinct_id="user",
                event="$rageclick",
                properties={"$session_id": session_b},
                team=self.team,
                timestamp=datetime.now() - timedelta(days=1),
            )
        _create_event(
            distinct_id="user",
            event="$exception",
            properties={"$session_id": session_b},
            team=self.team,
            timestamp=datetime.now() - timedelta(days=1),
        )

        # session_c: 3 rage clicks + 2 exceptions = score 13
        session_c = str(uuid7())
        for _ in range(3):
            _create_event(
                distinct_id="user",
                event="$rageclick",
                properties={"$session_id": session_c},
                team=self.team,
                timestamp=datetime.now() - timedelta(days=1),
            )
        for _ in range(2):
            _create_event(
                distinct_id="user",
                event="$exception",
                properties={"$session_id": session_c},
                team=self.team,
                timestamp=datetime.now() - timedelta(days=1),
            )

        flush_persons_and_events()

        source = FrustrationSignalsPlaylistSource()
        session_ids = source.get_session_ids(self.team, self.user)

        # session_c (score 13) > session_b (score 8) > session_a (score 6)
        assert session_ids == [session_c, session_b, session_a]

    def test_frustrated_sessions_excludes_old_data(self) -> None:
        cache.clear()

        old_session = str(uuid7())
        _create_event(
            distinct_id="user",
            event="$rageclick",
            properties={"$session_id": old_session},
            team=self.team,
            timestamp=datetime.now() - timedelta(days=10),
        )
        flush_persons_and_events()

        source = FrustrationSignalsPlaylistSource()
        session_ids = source.get_session_ids(self.team, self.user)
        assert old_session not in session_ids

    def test_frustrated_sessions_caching(self) -> None:
        cache.clear()

        session_id = str(uuid7())
        for _ in range(2):
            _create_event(
                distinct_id="user",
                event="$rageclick",
                properties={"$session_id": session_id},
                team=self.team,
                timestamp=datetime.now() - timedelta(days=1),
            )
        flush_persons_and_events()

        cache_key = FrustrationSignalsPlaylistSource._get_cache_key(self.team.pk)
        assert cache.get(cache_key) is None

        source = FrustrationSignalsPlaylistSource()
        session_ids = source.get_session_ids(self.team, self.user)
        assert session_id in session_ids
        assert cache.get(cache_key) is not None

    def test_frustrated_sessions_count(self) -> None:
        cache.clear()

        for _ in range(3):
            session_id = str(uuid7())
            for _ in range(2):
                _create_event(
                    distinct_id="user",
                    event="$rageclick",
                    properties={"$session_id": session_id},
                    team=self.team,
                    timestamp=datetime.now() - timedelta(days=1),
                )
        flush_persons_and_events()

        source = FrustrationSignalsPlaylistSource()
        count = source.count_session_ids(self.team, self.user)
        assert count == 3

    def test_frustrated_sessions_pagination(self) -> None:
        cache.clear()

        for i in range(5):
            session_id = str(uuid7())
            # Create varying rage clicks so ordering is deterministic, all above MIN_FRUSTRATION_SCORE
            for _ in range(6 - i):
                _create_event(
                    distinct_id="user",
                    event="$rageclick",
                    properties={"$session_id": session_id},
                    team=self.team,
                    timestamp=datetime.now() - timedelta(days=1),
                )
        flush_persons_and_events()

        source = FrustrationSignalsPlaylistSource()
        page1 = source.get_session_ids(self.team, self.user, limit=2, offset=0)
        page2 = source.get_session_ids(self.team, self.user, limit=2, offset=2)
        page3 = source.get_session_ids(self.team, self.user, limit=2, offset=4)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

        all_pages = page1 + page2 + page3
        assert len(set(all_pages)) == 5
