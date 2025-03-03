from datetime import datetime, timedelta
import json
from unittest import mock
from unittest.mock import MagicMock, patch
from ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters import (
    count_recordings_that_match_playlist_filters,
)
from posthog.redis import get_client
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.test.base import APIBaseTest


class TestRecordingsThatMatchPlaylistFilters(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.redis_client = get_client()

    @patch("posthoganalytics.capture_exception")
    def test_no_exception_for_unmatched_playlist(self, mock_capture_exception: MagicMock):
        count_recordings_that_match_playlist_filters(12345)
        assert self.redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}there_is_no_short_id") is None
        mock_capture_exception.assert_not_called()

    @patch("posthoganalytics.capture_exception")
    @patch("ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters.list_recordings_from_query")
    def test_count_recordings_that_match_no_recordings(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        mock_list_recordings_from_query.return_value = ([], False, None)

        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()

        assert json.loads(self.redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}")) == {
            "session_ids": [],
            "previous_ids": None,
            "has_more": False,
            "refreshed_at": mock.ANY,
        }

    @patch("posthoganalytics.capture_exception")
    @patch("ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters.list_recordings_from_query")
    def test_count_recordings_that_match_recordings(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        mock_list_recordings_from_query.return_value = (
            [
                SessionRecording.objects.create(
                    team=self.team,
                    session_id="123",
                )
            ],
            True,
            None,
        )
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()

        assert json.loads(self.redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}")) == {
            "session_ids": ["123"],
            "previous_ids": None,
            "has_more": True,
            "refreshed_at": mock.ANY,
        }

    @patch("posthoganalytics.capture_exception")
    @patch("ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters.list_recordings_from_query")
    def test_count_recordings_that_match_recordings_records_previous_ids(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        mock_list_recordings_from_query.return_value = (
            [
                SessionRecording.objects.create(
                    team=self.team,
                    session_id="123",
                )
            ],
            True,
            None,
        )
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        self.redis_client.set(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", json.dumps({"session_ids": ["245"], "has_more": True})
        )
        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()

        assert json.loads(self.redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}")) == {
            "session_ids": ["123"],
            "has_more": True,
            "previous_ids": ["245"],
            "refreshed_at": mock.ANY,
        }

    @patch("posthoganalytics.capture_exception")
    @patch("ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters.list_recordings_from_query")
    def test_count_recordings_that_match_recordings_skips_cooldown(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        mock_list_recordings_from_query.return_value = ([], False, None)

        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        existing_value = {"refreshed_at": (datetime.now() - timedelta(seconds=3600)).isoformat()}
        self.redis_client.set(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", json.dumps(existing_value))

        count_recordings_that_match_playlist_filters(playlist.id)

        mock_list_recordings_from_query.assert_not_called()
        mock_capture_exception.assert_not_called()

        assert self.redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}").decode("utf-8") == json.dumps(
            existing_value
        )
