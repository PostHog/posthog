import json
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
            "has_more": False,
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
            "has_more": True,
        }
