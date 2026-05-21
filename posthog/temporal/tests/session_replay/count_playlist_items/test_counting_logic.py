import json
import random
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
from unittest import mock
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.schema import (
    FilterLogicalOperator,
    PropertyOperator,
    RecordingOrder,
    RecordingPropertyFilter,
    RecordingsQuery,
)

from posthog.helpers.session_recording_playlist_templates import DEFAULT_PLAYLIST_NAMES
from posthog.redis import get_client
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.temporal.session_replay.count_playlist_items.counting_logic import (
    DEFAULT_RECORDING_FILTERS,
    count_recordings_that_match_playlist_filters,
    fetch_playlists_to_count,
)


class TestRecordingsThatMatchPlaylistFilters(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()
        self.redis_client = get_client()

    @patch("posthoganalytics.capture_exception")
    def test_no_exception_for_unmatched_playlist(self, mock_capture_exception: MagicMock):
        count_recordings_that_match_playlist_filters(12345)
        assert self.redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}there_is_no_short_id") is None
        mock_capture_exception.assert_not_called()

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
    def test_count_recordings_that_match_no_recordings(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        mock_list_recordings_from_query.return_value = ([], False, None, None)

        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()

        assert self._get_counts_from_redis(playlist) == {
            "version": 2,
            "session_ids": [],
            "sessions_with_expiry": {},
            "previous_ids": None,
            "has_more": False,
            "refreshed_at": mock.ANY,
            "error_count": 0,
            "errored_at": None,
        }

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
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
            None,
        )
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()

        assert self._get_counts_from_redis(playlist) == {
            "version": 2,
            "session_ids": ["123"],
            "sessions_with_expiry": {"123": None},
            "previous_ids": None,
            "has_more": True,
            "refreshed_at": mock.ANY,
            "error_count": 0,
            "errored_at": None,
        }

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
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

        assert self._get_counts_from_redis(playlist) == {
            "version": 2,
            "session_ids": ["123"],
            "sessions_with_expiry": {"123": None},
            "has_more": True,
            "previous_ids": ["245"],
            "refreshed_at": mock.ANY,
            "error_count": 0,
            "errored_at": None,
        }

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
    def test_count_recordings_that_match_recordings_skips_cooldown(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        mock_list_recordings_from_query.return_value = ([], False, None, None)

        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        existing_value = {"refreshed_at": (timezone.now() - timedelta(seconds=3600)).isoformat()}
        self.redis_client.set(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", json.dumps(existing_value))

        count_recordings_that_match_playlist_filters(playlist.id)

        mock_list_recordings_from_query.assert_not_called()
        mock_capture_exception.assert_not_called()

        assert self._get_counts_from_redis(playlist) == existing_value

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
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
        mock_list_recordings_from_query.return_value = ([], False, None, None)

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
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
    def test_skips_default_filters(self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock):
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters=DEFAULT_RECORDING_FILTERS,
        )
        count_recordings_that_match_playlist_filters(playlist.id)
        mock_capture_exception.assert_not_called()
        mock_list_recordings_from_query.assert_not_called()

    @snapshot_postgres_queries
    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
    def test_sorts_nulls_first_and_then_least_recently_counted(
        self, _mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        with freeze_time("2024-01-01T12:00:00Z"):
            playlist1 = SessionRecordingPlaylist.objects.create(
                team=self.team,
                name="test1",
                filters={"date_from": "-21d"},
                last_counted_at=timezone.now() - timedelta(days=2),
            )

            playlist2 = SessionRecordingPlaylist.objects.create(
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

            playlist4 = SessionRecordingPlaylist.objects.create(
                team=self.team, name="test4", filters={"date_from": "-21d"}, last_counted_at=None
            )

            playlist_ids = fetch_playlists_to_count()
            mock_capture_exception.assert_not_called()

            assert len(playlist_ids) == 3
            assert playlist_ids == [playlist4.id, playlist1.id, playlist2.id]

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
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

        mock_list_recordings_from_query.return_value = ([], False, None, None)
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

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
    def test_count_recordings_with_too_many_errors_skips(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        mock_list_recordings_from_query.return_value = ([], False, None, None)

        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        existing_value = {"error_count": 5}
        self.redis_client.set(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", json.dumps(existing_value))

        count_recordings_that_match_playlist_filters(playlist.id)

        mock_list_recordings_from_query.assert_not_called()
        mock_capture_exception.assert_not_called()

        assert self._get_counts_from_redis(playlist) == existing_value

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
    def test_count_recordings_with_too_recent_error_skips(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        mock_list_recordings_from_query.return_value = ([], False, None, None)

        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={},
        )
        existing_value = {"error_count": 4, "errored_at": (timezone.now() - timedelta(seconds=3600)).isoformat()}
        self.redis_client.set(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", json.dumps(existing_value))

        count_recordings_that_match_playlist_filters(playlist.id)

        mock_list_recordings_from_query.assert_not_called()
        mock_capture_exception.assert_not_called()

        assert self._get_counts_from_redis(playlist) == existing_value

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
    def test_count_recordings_only_queries_since_last_count(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={"date_from": "-21d"},
        )

        last_count_time = timezone.now() - timedelta(hours=2)

        self.redis_client.set(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}",
            json.dumps(
                {
                    "version": 2,
                    "session_ids": ["session1", "session2"],
                    "sessions_with_expiry": {
                        "session1": (timezone.now() + timedelta(days=10)).isoformat(),
                        "session2": (timezone.now() + timedelta(days=10)).isoformat(),
                    },
                    "has_more": False,
                    "refreshed_at": last_count_time.isoformat(),
                    "error_count": 0,
                    "errored_at": None,
                }
            ),
        )

        mock_list_recordings_from_query.return_value = (
            [
                SessionRecording.objects.create(
                    team=self.team,
                    session_id="session3",
                )
            ],
            False,
            None,
            None,
        )

        count_recordings_that_match_playlist_filters(playlist.id)

        recordings_query = mock_list_recordings_from_query.call_args[0][0]
        assert recordings_query.date_from == last_count_time.isoformat()
        assert recordings_query.date_to is None

        stored_data = self._get_counts_from_redis(playlist)
        assert sorted(stored_data["session_ids"]) == ["session1", "session2", "session3"]
        assert stored_data["version"] == 2
        assert stored_data["has_more"] is False
        assert stored_data["refreshed_at"] > last_count_time.isoformat()

        mock_capture_exception.assert_not_called()

    @patch("posthoganalytics.capture_exception")
    @patch("posthog.temporal.session_replay.count_playlist_items.counting_logic.list_recordings_from_query")
    def test_unversioned_cached_data_triggers_full_query(
        self, mock_list_recordings_from_query: MagicMock, mock_capture_exception: MagicMock
    ):
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test",
            filters={"date_from": "-21d"},
        )

        last_count_time = timezone.now() - timedelta(hours=2)

        self.redis_client.set(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}",
            json.dumps(
                {
                    "session_ids": ["session1", "session2"],
                    "has_more": False,
                    "refreshed_at": last_count_time.isoformat(),
                    "error_count": 0,
                    "errored_at": None,
                }
            ),
        )

        new_recording = SessionRecording(session_id="session3", team=self.team)
        new_recording.expiry_time = timezone.now() + timedelta(days=10)
        mock_list_recordings_from_query.return_value = ([new_recording], False, None, None)

        count_recordings_that_match_playlist_filters(playlist.id)

        recordings_query = mock_list_recordings_from_query.call_args[0][0]
        assert recordings_query.date_from == "-21d"

        stored_data = self._get_counts_from_redis(playlist)
        assert stored_data["session_ids"] == ["session3"]
        assert stored_data["version"] == 2

        mock_capture_exception.assert_not_called()

    def _get_counts_from_redis(self, playlist: SessionRecordingPlaylist) -> dict:
        counts = self.redis_client.get(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}")
        assert counts is not None
        return json.loads(counts.decode("utf-8"))

    def test_excludes_default_template_playlists(self):
        # need to type ignore here, because mypy insists this returns a list but it does not
        default_name: str = random.choice(DEFAULT_PLAYLIST_NAMES)  # type: ignore
        SessionRecordingPlaylist.objects.create(
            team=self.team,
            name=default_name,
            last_counted_at=None,
            filters={"date_from": "-21d"},
        )
        playlist_ids = fetch_playlists_to_count()
        assert len(playlist_ids) == 0

    def test_excludes_playlists_with_pinned_items(self):
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="has pinned",
            filters={"date_from": "-21d"},
            last_counted_at=None,
        )
        SessionRecordingPlaylistItem.objects.create(
            playlist=playlist,
            session_id="123",
        )
        playlist_ids = fetch_playlists_to_count()
        assert playlist.id not in playlist_ids
