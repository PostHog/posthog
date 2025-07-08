from unittest.mock import patch, MagicMock
from django.utils import timezone

from posthog.models import User
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from posthog.tasks.session_recordings import bulk_delete_recordings_task
from posthog.test.base import BaseTest, ClickhouseTestMixin
from pydantic import ValidationError


class TestSessionRecordingsTasks(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user = User.objects.create_user(
            email="test@posthog.com",
            password="password123",
            first_name="Test",
            last_name="User",
        )

    def test_bulk_delete_recordings_task_success(self) -> None:
        """
        Test successful bulk deletion of recordings and associated playlist items
        """
        # Create test recordings
        recording1 = SessionRecording.objects.create(
            team=self.team,
            session_id="session-1",
            distinct_id="user-1",
            deleted=False,
        )
        recording2 = SessionRecording.objects.create(
            team=self.team,
            session_id="session-2",
            distinct_id="user-2",
            deleted=False,
        )

        # Create test playlist and add recordings to it
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Test Playlist",
            created_by=self.user,
            created_at=timezone.now(),
        )

        # Add recordings to playlist
        playlist_item1 = SessionRecordingPlaylistItem.objects.create(
            playlist=playlist,
            recording=recording1,
            deleted=False,
        )
        playlist_item2 = SessionRecordingPlaylistItem.objects.create(
            playlist=playlist,
            recording=recording2,
            deleted=False,
        )

        # Mock list_recordings_from_query to return the test recordings
        mock_recordings = [recording1, recording2]

        with patch("posthog.tasks.session_recordings.list_recordings_from_query") as mock_list_recordings:
            mock_list_recordings.return_value = (mock_recordings, False, "")

            # Execute the task
            result = bulk_delete_recordings_task(
                team_id=self.team.id,
                user_id=self.user.id,
                filters={"properties": []},  # Empty for now to match all
                user_distinct_id=self.user.distinct_id,
            )

        # Verify recordings are marked as deleted
        recording1.refresh_from_db()
        recording2.refresh_from_db()
        self.assertTrue(recording1.deleted)
        self.assertTrue(recording2.deleted)

        # Verify playlist items are marked as deleted
        playlist_item1.refresh_from_db()
        playlist_item2.refresh_from_db()
        self.assertTrue(playlist_item1.deleted)
        self.assertTrue(playlist_item2.deleted)

        # Verify task result
        self.assertEqual(result["deleted_count"], 2)
        self.assertEqual(result["playlist_items_deleted_count"], 2)
        self.assertIn("Successfully deleted 2 recordings", result["message"])

    def test_bulk_delete_recordings_task_no_recordings_found(self) -> None:
        """Test when no recordings match the filters"""
        with patch("posthog.tasks.session_recordings.list_recordings_from_query") as mock_list_recordings:
            mock_list_recordings.return_value = ([], False, "")

            result = bulk_delete_recordings_task(
                team_id=self.team.id,
                user_id=self.user.id,
                filters={"properties": []},
                user_distinct_id=str(self.user.distinct_id),
            )

        self.assertEqual(result["deleted_count"], 0)
        self.assertEqual(result["message"], "No recordings found matching the provided filters")

    def test_bulk_delete_recordings_task_clickhouse_only_recordings(self) -> None:
        """Test deletion of recordings that exist only in ClickHouse (not in PostgreSQL)"""
        # Create mock recordings that would come from ClickHouse
        mock_recording = MagicMock()
        mock_recording.session_id = "ch-only-session"
        mock_recording.distinct_id = "ch-user"
        mock_recording.team = self.team
        mock_recording.deleted = False
        mock_recordings = [mock_recording]

        with patch("posthog.tasks.session_recordings.list_recordings_from_query") as mock_list_recordings:
            mock_list_recordings.return_value = (mock_recordings, False, "")

            result = bulk_delete_recordings_task(
                team_id=self.team.id,
                user_id=self.user.id,
                filters={"properties": []},
                user_distinct_id=str(self.user.distinct_id),
            )

        # Verify a new SessionRecording was created with deleted=True
        created_recording = SessionRecording.objects.get(team=self.team, session_id="ch-only-session")
        self.assertTrue(created_recording.deleted)
        self.assertEqual(created_recording.distinct_id, "ch-user")

        self.assertEqual(result["deleted_count"], 1)

    def test_bulk_delete_recordings_task_chunking(self) -> None:
        """Test that large datasets are processed in chunks"""
        # Create many mock recordings to test chunking
        mock_recordings = []
        for i in range(250):  # More than chunk size (100)
            mock_recording = MagicMock()
            mock_recording.session_id = f"session-{i}"
            mock_recording.distinct_id = f"user-{i}"
            mock_recordings.append(mock_recording)

        with patch("posthog.tasks.session_recordings.list_recordings_from_query") as mock_list_recordings:
            mock_list_recordings.return_value = (mock_recordings, False, "")

            # Mock the task's update_state method
            with patch(
                "posthog.tasks.session_recordings.bulk_delete_recordings_task.update_state"
            ) as mock_update_state:
                result = bulk_delete_recordings_task(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    filters={"properties": []},
                    user_distinct_id=str(self.user.distinct_id),
                )

            # Verify task called update_state for progress (should be called 3 times for 3 chunks)
            self.assertEqual(mock_update_state.call_count, 3)

            # Verify all recordings were processed
            self.assertEqual(result["deleted_count"], 250)

    @patch("posthog.tasks.session_recordings.report_user_action")
    def test_bulk_delete_recordings_task_user_action_logged(self, mock_report_user_action: MagicMock) -> None:
        """Test that user action is properly logged"""
        recording = SessionRecording.objects.create(
            team=self.team, session_id="session-1", distinct_id="user-1", deleted=False
        )

        with patch("posthog.tasks.session_recordings.list_recordings_from_query") as mock_list_recordings:
            mock_list_recordings.return_value = ([recording], False, "")

            bulk_delete_recordings_task(
                team_id=self.team.id,
                user_id=self.user.id,
                filters={"properties": []},
                user_distinct_id=str(self.user.distinct_id),
            )

        # Verify user action was reported
        mock_report_user_action.assert_called_once()
        call_args = mock_report_user_action.call_args

        self.assertEqual(call_args[1]["user"], self.user)
        self.assertEqual(call_args[1]["event"], "bulk_delete_recordings")
        self.assertEqual(call_args[1]["team"], self.team)

        properties = call_args[1]["properties"]
        self.assertEqual(properties["deleted_count"], 1)
        self.assertEqual(properties["team_id"], self.team.id)
        self.assertEqual(properties["user_id"], self.user.id)

    def test_bulk_delete_recordings_task_invalid_filters(self) -> None:
        """Test error handling for invalid filters"""

        with self.assertRaises(ValidationError):
            bulk_delete_recordings_task(
                team_id=self.team.id,
                user_id=self.user.id,
                filters={"invalid": "filter structure"},
                user_distinct_id=str(self.user.distinct_id),
            )

    @patch("posthog.tasks.session_recordings.logger")
    def test_bulk_delete_recordings_task_progress_logging(self, mock_logger: MagicMock) -> None:
        """Test that progress is properly logged"""
        recording = SessionRecording.objects.create(
            team=self.team, session_id="session-1", distinct_id="user-1", deleted=False
        )

        with patch("posthog.tasks.session_recordings.list_recordings_from_query") as mock_list_recordings:
            mock_list_recordings.return_value = ([recording], False, "")

            bulk_delete_recordings_task(
                team_id=self.team.id,
                user_id=self.user.id,
                filters={"properties": []},
                user_distinct_id=str(self.user.distinct_id),
            )

        # Verify progress and completion were logged
        mock_logger.info.assert_any_call(
            "bulk_delete_recordings_task_progress",
            team_id=self.team.id,
            user_id=self.user.id,
            current=1,
            total=1,
            playlist_items_deleted=0,
        )

        mock_logger.info.assert_any_call(
            "bulk_delete_recordings_task_completed",
            team_id=self.team.id,
            user_id=self.user.id,
            current=1,
            total=1,
            playlist_items_deleted=0,
        )
