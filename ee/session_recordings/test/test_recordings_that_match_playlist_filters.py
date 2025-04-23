from datetime import datetime, timedelta
import json
from unittest import mock
from unittest.mock import MagicMock, patch
from ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters import (
    DEFAULT_RECORDING_FILTERS,
    count_recordings_that_match_playlist_filters,
    enqueue_recordings_that_match_playlist_filters,
)
from posthog.redis import get_client
from posthog.schema import (
    FilterLogicalOperator,
    PropertyOperator,
    RecordingOrder,
    RecordingPropertyFilter,
    RecordingsQuery,
)
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.test.base import APIBaseTest
from django.utils import timezone


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

    @patch("posthoganalytics.capture_exception")
    @patch("ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters.list_recordings_from_query")
    def test_matching_legacy_filters(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        """
        This is a regression test, we have playlists with legacy filters that we want to make sure still work
        """
        legacy_filters = {
            "events": [],
            "actions": [],
            "date_from": "-21d",
            "properties": [],
            "session_recording_duration": {"key": "duration", "type": "recording", "value": 60, "operator": "gt"},
        }

        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters=legacy_filters,
        )
        mock_list_recordings_from_query.return_value = ([], False, None)

        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()

        playlist.refresh_from_db()
        assert playlist.filters == {
            "date_from": "-21d",
            "date_to": None,
            "duration": [
                {
                    "key": "duration",
                    "type": "recording",
                    "value": 60,
                    "operator": "gt",
                }
            ],
            "filter_group": {
                "type": FilterLogicalOperator.AND_,
                "values": [
                    {"type": FilterLogicalOperator.AND_, "values": []},
                ],
            },
            "filter_test_accounts": False,
            "order": RecordingOrder.START_TIME,
        }

        assert mock_list_recordings_from_query.call_args[0] == (
            RecordingsQuery(
                actions=[],
                console_log_filters=[],
                date_from="-21d",
                date_to=None,
                events=[],
                filter_test_accounts=False,
                having_predicates=[
                    RecordingPropertyFilter(
                        key="duration", label=None, operator=PropertyOperator.GT, type="recording", value=60.0
                    )
                ],
                kind="RecordingsQuery",
                limit=None,
                modifiers=None,
                offset=None,
                operand=FilterLogicalOperator.AND_,
                order=RecordingOrder.START_TIME,
                person_uuid=None,
                properties=[],
                response=None,
                session_ids=None,
                user_modified_filters=None,
            ),
        )

    @patch("posthoganalytics.capture_exception")
    @patch("ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters.list_recordings_from_query")
    def test_skips_default_filters(self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock):
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters=DEFAULT_RECORDING_FILTERS,
        )
        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()
        mock_list_recordings_from_query.assert_not_called()

    @patch("posthoganalytics.capture_exception")
    @patch("ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters.list_recordings_from_query")
    def test_sorts_nulls_first_and_then_least_recently_counted(
        self, _mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test1",
            filters={"date_from": "-21d"},
            last_counted_at=timezone.now() - timedelta(days=2),
        )

        SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test2",
            filters={"date_from": "-21d"},
            last_counted_at=timezone.now() - timedelta(days=1),
        )

        # too recently counted won't be counted
        SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test3",
            filters={"date_from": "-21d"},
            last_counted_at=timezone.now() - timedelta(hours=1),
        )

        SessionRecordingPlaylist.objects.create(
            team=self.team, name="test4", filters={"date_from": "-21d"}, last_counted_at=None
        )

        enqueue_recordings_that_match_playlist_filters()
        mock_capture_exception.assert_not_called()

    @patch("posthoganalytics.capture_exception")
    @patch("ee.session_recordings.playlist_counters.recordings_that_match_playlist_filters.list_recordings_from_query")
    def test_template_rageclick_filter_should_process(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ) -> None:
        """
        This is a regression test, we saw this failing in prod
        """
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={
                "order": "start_time",
                "date_to": None,
                "duration": [{"key": "active_seconds", "type": "recording", "value": 5, "operator": "gt"}],
                "date_from": "-3d",
                "filter_group": {
                    "type": "AND",
                    "values": [{"type": "AND", "values": [{"id": "$rageclick", "type": "events", "order": 0}]}],
                },
                "filter_test_accounts": False,
            },
        )

        mock_list_recordings_from_query.return_value = ([], False, None)
        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()

        assert mock_list_recordings_from_query.call_args[0] == (
            RecordingsQuery(
                actions=[],
                console_log_filters=[],
                date_from="-3d",
                date_to=None,
                events=[
                    {
                        "id": "$rageclick",
                        "type": "events",
                        "order": 0,
                    }
                ],
                filter_test_accounts=False,
                having_predicates=[
                    RecordingPropertyFilter(
                        key="active_seconds", label=None, operator=PropertyOperator.GT, type="recording", value=5.0
                    )
                ],
                kind="RecordingsQuery",
                limit=None,
                modifiers=None,
                offset=None,
                operand=FilterLogicalOperator.AND_,
                order=RecordingOrder.START_TIME,
                person_uuid=None,
                properties=[],
                response=None,
                session_ids=None,
                user_modified_filters=None,
            ),
        )
