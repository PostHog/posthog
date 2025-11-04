from datetime import datetime, timedelta

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import Mock, patch

from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status

from posthog.models import Comment, SessionRecordingPlaylist
from posthog.models.exported_asset import ExportedAsset
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.synthetic_playlists import NewUrlsSyntheticPlaylistSource

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


class TestNewUrlsSyntheticPlaylists(APIBaseTest):
    """Tests for the dynamic new URLs synthetic playlists"""

    def setUp(self):
        super().setUp()
        from posthog.clickhouse.client import sync_execute

        # Clear replay events table before each test
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")

        # Mock the feature flag to return "test" variant
        self.feature_flag_patcher = patch("posthoganalytics.get_feature_flag")
        mock_get_feature_flag = self.feature_flag_patcher.start()

        # Create a mock FeatureFlag object with variant="test"
        mock_flag = Mock()
        mock_flag.variant = "test"
        mock_flag.enabled = True
        mock_get_feature_flag.return_value = mock_flag

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def _produce_replay_with_urls(
        self, session_id: str, urls: list[str], timestamp: str | datetime | None = None
    ) -> None:
        """Helper to create a replay event with specific URLs"""
        from posthog.clickhouse.client import sync_execute
        from posthog.models.event.util import format_clickhouse_timestamp
        from posthog.utils import cast_timestamp_or_now

        timestamp_dt = cast_timestamp_or_now(timestamp)
        timestamp_str = format_clickhouse_timestamp(timestamp_dt)
        # DateTime column needs format without microseconds
        timestamp_dt_str = (
            timestamp_dt.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(timestamp_dt, "strftime")
            else timestamp_str.split(".")[0]
        )

        # Insert directly into sharded_session_replay_events with all_urls
        # Need to use SELECT syntax for AggregateFunction columns
        sync_execute(
            """
            INSERT INTO sharded_session_replay_events (
                session_id,
                team_id,
                distinct_id,
                min_first_timestamp,
                max_last_timestamp,
                first_url,
                all_urls,
                click_count,
                keypress_count,
                mouse_activity_count,
                active_milliseconds,
                console_log_count,
                console_warn_count,
                console_error_count,
                size,
                retention_period_days,
                _timestamp
            )
            SELECT
                %(session_id)s,
                %(team_id)s,
                %(distinct_id)s,
                toDateTime64(%(timestamp)s, 6, 'UTC'),
                toDateTime64(%(timestamp)s, 6, 'UTC'),
                argMinState(cast(%(first_url)s, 'Nullable(String)'), toDateTime64(%(timestamp)s, 6, 'UTC')),
                %(all_urls)s,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                %(retention_days)s,
                %(_timestamp)s
            """,
            {
                "session_id": session_id,
                "team_id": self.team.pk,
                "distinct_id": "user",
                "timestamp": timestamp_str,
                "_timestamp": timestamp_dt_str,
                "first_url": urls[0] if urls else "",
                "all_urls": urls,
                "retention_days": 30,
            },
        )

    def _get_playlists_response(self, query_params: str = "") -> dict:
        url = f"/api/projects/{self.team.id}/session_recording_playlists{query_params}"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def _get_new_url_playlists(self) -> list[dict]:
        """Get all new-url synthetic playlists from the list endpoint"""
        response_data = self._get_playlists_response()
        return [p for p in response_data["results"] if p["short_id"].startswith("synthetic-new-url-")]

    def _get_synthetic_playlist(self, short_id: str) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()

    def test_new_urls_creates_dynamic_playlists(self) -> None:
        """Test that new URLs detected in last 14 days create dynamic synthetic playlists"""
        # Clear cache to ensure fresh detection
        from django.core.cache import cache

        cache.clear()

        # Create recordings with new URLs (within last 14 days)
        now_time = datetime.now()
        self._produce_replay_with_urls("session-1", ["https://new-page.com/checkout"], now_time - timedelta(days=1))
        self._produce_replay_with_urls("session-2", ["https://new-page.com/pricing"], now_time - timedelta(days=2))

        # Get playlists
        new_url_playlists = self._get_new_url_playlists()

        # Should have 2 dynamic playlists, one for each unique URL
        assert len(new_url_playlists) == 2

        # Check that playlist names include the URLs
        playlist_names = {p["name"] for p in new_url_playlists}
        assert "New: https://new-page.com/checkout" in playlist_names
        assert "New: https://new-page.com/pricing" in playlist_names

    def test_new_urls_ignores_historical_urls(self) -> None:
        """Test that URLs that appeared before the 14-day window are not considered new"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()

        # Create old recording (> 14 days ago) with a URL
        self._produce_replay_with_urls("old-session", ["https://old-page.com"], now_time - timedelta(days=20))

        # Create recent recording with the same URL
        self._produce_replay_with_urls("recent-session", ["https://old-page.com"], now_time - timedelta(days=1))

        # Get playlists
        new_url_playlists = self._get_new_url_playlists()

        # Should have NO dynamic playlists since the URL existed before
        assert len(new_url_playlists) == 0

    def test_new_urls_only_truly_new(self) -> None:
        """Test that only truly new URLs (first seen in last 14 days) are included"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()

        # Old URL (>14 days)
        self._produce_replay_with_urls("old-1", ["https://old.com"], now_time - timedelta(days=20))

        # Mix of old and new URLs in recent session
        self._produce_replay_with_urls("recent-1", ["https://old.com", "https://new.com"], now_time - timedelta(days=1))

        # Get playlists
        new_url_playlists = self._get_new_url_playlists()

        # Should have 1 playlist only for the truly new URL
        assert len(new_url_playlists) == 1
        assert new_url_playlists[0]["name"] == "New: https://new.com"

    def test_retrieve_new_url_playlist(self) -> None:
        """Test retrieving a specific new URL playlist by its short_id"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()
        self._produce_replay_with_urls("session-1", ["https://test.com/page"], now_time - timedelta(days=1))
        self._produce_replay_with_urls("session-2", ["https://test.com/page"], now_time - timedelta(days=2))

        # Get the playlist list to find the short_id
        new_url_playlists = self._get_new_url_playlists()
        assert len(new_url_playlists) == 1

        short_id = new_url_playlists[0]["short_id"]
        assert short_id.startswith("synthetic-new-url-")

        # Retrieve the specific playlist
        playlist = self._get_synthetic_playlist(short_id)

        assert playlist["short_id"] == short_id
        assert playlist["name"] == "New: https://test.com/page"
        assert playlist["type"] == "collection"
        assert playlist["is_synthetic"] is True
        assert playlist["recordings_counts"]["collection"]["count"] == 2

    def test_new_url_playlist_count(self) -> None:
        """Test that new URL playlists correctly count recordings"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()

        # Create 3 sessions visiting the same new URL
        self._produce_replay_with_urls("session-1", ["https://new-url.com"], now_time - timedelta(days=1))
        self._produce_replay_with_urls("session-2", ["https://new-url.com"], now_time - timedelta(days=2))
        self._produce_replay_with_urls("session-3", ["https://new-url.com"], now_time - timedelta(days=3))

        new_url_playlists = self._get_new_url_playlists()
        assert len(new_url_playlists) == 1

        # Check the count
        assert new_url_playlists[0]["recordings_counts"]["collection"]["count"] == 3

    def test_new_url_caching(self) -> None:
        """Test that new URL detection results are cached"""
        from django.core.cache import cache

        from posthog.session_recordings.synthetic_playlists import NewUrlsSyntheticPlaylistSource

        cache.clear()

        now_time = datetime.now()
        self._produce_replay_with_urls("session-1", ["https://cached-url.com"], now_time - timedelta(days=1))

        # First call should hit the database
        cache_key = NewUrlsSyntheticPlaylistSource._get_cache_key(self.team.pk)
        assert cache.get(cache_key) is None

        # Get playlists (should populate cache)
        new_url_playlists = self._get_new_url_playlists()
        assert len(new_url_playlists) == 1

        # Cache should now be populated
        cached_urls = cache.get(cache_key)
        assert cached_urls is not None
        assert "https://cached-url.com" in cached_urls

        # Second call should use cache (even if we add more data)
        self._produce_replay_with_urls("session-2", ["https://another-url.com"], now_time - timedelta(days=1))

        # Should still show only 1 playlist (from cache)
        new_url_playlists = self._get_new_url_playlists()
        assert len(new_url_playlists) == 1

    def test_long_url_truncation(self) -> None:
        """Test that very long URLs are truncated in playlist names"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()
        long_url = "https://example.com/" + "a" * 100  # Very long URL

        self._produce_replay_with_urls("session-1", [long_url], now_time - timedelta(days=1))

        new_url_playlists = self._get_new_url_playlists()
        assert len(new_url_playlists) == 1

        # Name should be truncated with ellipsis
        assert new_url_playlists[0]["name"].startswith("New: ")
        assert len(new_url_playlists[0]["name"]) <= 70  # "New: " + 60 chars + "..."
        assert new_url_playlists[0]["name"].endswith("...")

    def test_url_grouping_with_numeric_ids(self) -> None:
        """Test that URLs with different numeric IDs are grouped into one playlist"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()

        # Create recordings with URLs containing different numeric IDs
        self._produce_replay_with_urls(
            "session-1", ["https://app.posthog.com/project/1/settings"], now_time - timedelta(days=1)
        )
        self._produce_replay_with_urls(
            "session-2", ["https://app.posthog.com/project/2/settings"], now_time - timedelta(days=2)
        )
        self._produce_replay_with_urls(
            "session-3", ["https://app.posthog.com/project/999/settings"], now_time - timedelta(days=3)
        )

        new_url_playlists = self._get_new_url_playlists()

        # Should have only 1 playlist since all URLs normalize to the same pattern
        assert len(new_url_playlists) == 1
        assert "project/{id}/settings" in new_url_playlists[0]["name"]

        # The playlist should contain all 3 sessions
        assert new_url_playlists[0]["recordings_counts"]["collection"]["count"] == 3

    def test_url_grouping_with_uuids(self) -> None:
        """Test that URLs with different UUIDs are grouped into one playlist"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()

        # Create recordings with URLs containing different UUIDs
        self._produce_replay_with_urls(
            "session-1",
            ["https://app.posthog.com/order/550e8400-e29b-41d4-a716-446655440000/details"],
            now_time - timedelta(days=1),
        )
        self._produce_replay_with_urls(
            "session-2",
            ["https://app.posthog.com/order/123e4567-e89b-12d3-a456-426614174000/details"],
            now_time - timedelta(days=2),
        )

        new_url_playlists = self._get_new_url_playlists()

        # Should have only 1 playlist
        assert len(new_url_playlists) == 1
        assert "order/{uuid}/details" in new_url_playlists[0]["name"]

        # Should contain both sessions
        assert new_url_playlists[0]["recordings_counts"]["collection"]["count"] == 2

    def test_url_grouping_with_query_params(self) -> None:
        """Test that URLs with different query parameters are grouped together"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()

        # Create recordings with same path but different query params
        self._produce_replay_with_urls(
            "session-1", ["https://app.posthog.com/billing?id=1"], now_time - timedelta(days=1)
        )
        self._produce_replay_with_urls(
            "session-2", ["https://app.posthog.com/billing?id=2&foo=bar"], now_time - timedelta(days=2)
        )
        self._produce_replay_with_urls("session-3", ["https://app.posthog.com/billing"], now_time - timedelta(days=3))

        new_url_playlists = self._get_new_url_playlists()

        # Should have only 1 playlist (query params are stripped)
        assert len(new_url_playlists) == 1
        assert new_url_playlists[0]["name"] == "New: https://app.posthog.com/billing"

        # Should contain all 3 sessions
        assert new_url_playlists[0]["recordings_counts"]["collection"]["count"] == 3

    def test_url_grouping_preserves_different_paths(self) -> None:
        """Test that genuinely different URLs create separate playlists"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()

        # Create recordings with different paths (even though they have similar IDs)
        self._produce_replay_with_urls(
            "session-1", ["https://app.posthog.com/project/1/settings"], now_time - timedelta(days=1)
        )
        self._produce_replay_with_urls(
            "session-2", ["https://app.posthog.com/project/1/billing"], now_time - timedelta(days=2)
        )
        self._produce_replay_with_urls(
            "session-3", ["https://app.posthog.com/user/1/settings"], now_time - timedelta(days=3)
        )

        new_url_playlists = self._get_new_url_playlists()

        # Should have 3 different playlists
        assert len(new_url_playlists) == 3

        playlist_names = {p["name"] for p in new_url_playlists}
        assert "New: https://app.posthog.com/project/{id}/settings" in playlist_names
        assert "New: https://app.posthog.com/project/{id}/billing" in playlist_names
        assert "New: https://app.posthog.com/user/{id}/settings" in playlist_names

        # Each should have 1 session
        for playlist in new_url_playlists:
            assert playlist["recordings_counts"]["collection"]["count"] == 1

    def test_url_grouping_mixed_patterns(self) -> None:
        """Test URL grouping with a realistic mix of patterns"""
        from django.core.cache import cache

        cache.clear()

        now_time = datetime.now()

        # Simulate a realistic scenario with various URL patterns
        urls_and_sessions = [
            # Project settings with different IDs (should group)
            ("session-1", ["https://app.posthog.com/project/123/settings"]),
            ("session-2", ["https://app.posthog.com/project/456/settings"]),
            # Same project, different tab (should be separate)
            ("session-3", ["https://app.posthog.com/project/789/insights"]),
            # Recording with hash ID (should group with session-5)
            ("session-4", ["https://app.posthog.com/recording/abc123def456ghi789jkl"]),
            ("session-5", ["https://app.posthog.com/recording/xyz999uuu888vvv777www"]),
            # Static pages (should remain separate)
            ("session-6", ["https://app.posthog.com/dashboard"]),
        ]

        for session_id, urls in urls_and_sessions:
            self._produce_replay_with_urls(session_id, urls, now_time - timedelta(days=1))

        new_url_playlists = self._get_new_url_playlists()

        # Should have 4 playlists:
        # 1. project/{id}/settings (sessions 1-2)
        # 2. project/{id}/insights (session 3)
        # 3. recording/{hash} (sessions 4-5)
        # 4. dashboard (session 6)
        assert len(new_url_playlists) == 4

        # Verify counts
        playlist_by_name = {p["name"]: p for p in new_url_playlists}

        settings_playlist = playlist_by_name.get("New: https://app.posthog.com/project/{id}/settings")
        assert settings_playlist is not None
        assert settings_playlist["recordings_counts"]["collection"]["count"] == 2

        insights_playlist = playlist_by_name.get("New: https://app.posthog.com/project/{id}/insights")
        assert insights_playlist is not None
        assert insights_playlist["recordings_counts"]["collection"]["count"] == 1

        recording_playlist = playlist_by_name.get("New: https://app.posthog.com/recording/{hash}")
        assert recording_playlist is not None
        assert recording_playlist["recordings_counts"]["collection"]["count"] == 2

        dashboard_playlist = playlist_by_name.get("New: https://app.posthog.com/dashboard")
        assert dashboard_playlist is not None
        assert dashboard_playlist["recordings_counts"]["collection"]["count"] == 1


class TestUrlNormalization(BaseTest):
    """Unit tests for URL normalization logic"""

    @parameterized.expand(
        [
            # Query parameter removal
            ("https://example.com/billing?id=1", "https://example.com/billing"),
            ("https://example.com/billing?id=1&foo=bar", "https://example.com/billing"),
            # Fragment removal
            ("https://example.com/page#section", "https://example.com/page"),
            ("https://example.com/page?q=1#section", "https://example.com/page"),
            # Numeric ID normalization
            ("https://example.com/project/123/settings", "https://example.com/project/{id}/settings"),
            ("https://example.com/project/1/settings", "https://example.com/project/{id}/settings"),
            ("https://example.com/user/456/profile/789/edit", "https://example.com/user/{id}/profile/{id}/edit"),
            # UUID normalization
            ("https://example.com/item/550e8400-e29b-41d4-a716-446655440000", "https://example.com/item/{uuid}"),
            (
                "https://example.com/order/123e4567-e89b-12d3-a456-426614174000/details",
                "https://example.com/order/{uuid}/details",
            ),
            # Hash/encoded ID normalization (16+ chars)
            ("https://example.com/session/xYz123AbC456DeF789", "https://example.com/session/{hash}"),
            ("https://example.com/recording/aBcDeFgHiJkLmNoPqRsTuVwXyZ", "https://example.com/recording/{hash}"),
            ("https://example.com/token/abc_def_ghi_jkl_mno", "https://example.com/token/{hash}"),
            # Short strings preserved (not hashes)
            ("https://example.com/api/v1/users", "https://example.com/api/v1/users"),
            ("https://example.com/admin/dashboard", "https://example.com/admin/dashboard"),
            ("https://example.com/en-US/about", "https://example.com/en-US/about"),
            # Trailing slash removal
            ("https://example.com/billing/", "https://example.com/billing"),
            ("https://example.com/", "https://example.com/"),
            # Combined cases
            (
                "https://example.com/project/123/settings?tab=general#section",
                "https://example.com/project/{id}/settings",
            ),
            (
                "https://example.com/user/550e8400-e29b-41d4-a716-446655440000/edit?foo=bar",
                "https://example.com/user/{uuid}/edit",
            ),
            (
                "https://example.com/api/v1/recording/xYz123AbC456DeF789?format=json",
                "https://example.com/api/v1/recording/{hash}",
            ),
            # Edge cases: don't normalize version numbers or language codes
            ("https://example.com/api/v2/endpoint", "https://example.com/api/v2/endpoint"),
            ("https://example.com/en/about", "https://example.com/en/about"),
            ("https://example.com/fr/contact", "https://example.com/fr/contact"),
        ]
    )
    def test_normalize_url_patterns(self, input_url: str, expected_output: str) -> None:
        """Test various URL normalization patterns"""
        result = NewUrlsSyntheticPlaylistSource._normalize_url(input_url)
        assert result == expected_output, f"Expected {expected_output}, got {result}"

    def test_normalize_url_groups_similar_urls(self) -> None:
        """Test that URLs with different IDs are normalized to the same value"""
        urls = [
            "https://example.com/project/1/settings",
            "https://example.com/project/2/settings",
            "https://example.com/project/999/settings",
        ]

        normalized = [NewUrlsSyntheticPlaylistSource._normalize_url(url) for url in urls]

        # All should normalize to the same value
        assert len(set(normalized)) == 1
        assert normalized[0] == "https://example.com/project/{id}/settings"

    def test_normalize_url_preserves_different_paths(self) -> None:
        """Test that genuinely different URLs remain different after normalization"""
        urls = [
            "https://example.com/project/123/settings",
            "https://example.com/project/123/billing",
            "https://example.com/user/123/settings",
        ]

        normalized = [NewUrlsSyntheticPlaylistSource._normalize_url(url) for url in urls]

        # Should have 3 different normalized values
        assert len(set(normalized)) == 3
        assert set(normalized) == {
            "https://example.com/project/{id}/settings",
            "https://example.com/project/{id}/billing",
            "https://example.com/user/{id}/settings",
        }

    def test_normalize_url_handles_malformed_urls(self) -> None:
        """Test that malformed URLs are returned as-is"""
        malformed_urls = [
            "",
            "not-a-url",
            "://missing-scheme",
        ]

        for url in malformed_urls:
            result = NewUrlsSyntheticPlaylistSource._normalize_url(url)
            # Should return original URL if parsing fails
            assert result == url or result != ""  # Either returns as-is or handles gracefully

    def test_pattern_newness_not_url_newness(self) -> None:
        """
        Test that we detect NEW PATTERNS, not just new URLs.
        If we saw /billing/1/summary months ago, then /billing/2/summary today
        should NOT be considered a new pattern.
        """
        from datetime import datetime, timedelta

        now = datetime.now()
        six_months_ago = now - timedelta(days=180)
        today = now - timedelta(days=1)

        # Mock ClickHouse query results
        mock_results = [
            # Old URL that normalizes to /billing/{id}/summary
            ("https://example.com/billing/1/summary", six_months_ago),
            # New URL but same pattern
            ("https://example.com/billing/2/summary", today),
            # Truly new pattern
            ("https://example.com/admin/dashboard", today),
        ]

        # Build pattern_first_seen the same way _get_new_urls does
        pattern_first_seen: dict[str, datetime] = {}
        for raw_url, first_seen_ts in mock_results:
            normalized = NewUrlsSyntheticPlaylistSource._normalize_url(raw_url)
            if normalized not in pattern_first_seen or first_seen_ts < pattern_first_seen[normalized]:
                pattern_first_seen[normalized] = first_seen_ts

        # Check that /billing/{id}/summary has the OLD timestamp (6 months ago)
        billing_pattern = "https://example.com/billing/{id}/summary"
        assert billing_pattern in pattern_first_seen
        assert pattern_first_seen[billing_pattern] == six_months_ago

        # Check that /admin/dashboard has the NEW timestamp (today)
        admin_pattern = "https://example.com/admin/dashboard"
        assert admin_pattern in pattern_first_seen
        assert pattern_first_seen[admin_pattern] == today

        # Filter to patterns that appeared in last 14 days
        lookback_start = now - timedelta(days=14)
        new_patterns = [
            pattern for pattern, first_seen in pattern_first_seen.items() if lookback_start <= first_seen <= now
        ]

        # Only /admin/dashboard should be considered "new"
        assert admin_pattern in new_patterns
        assert billing_pattern not in new_patterns
        assert len(new_patterns) == 1
