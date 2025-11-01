import json

from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.tasks.feature_flags import (
    BATCH_SIZE,
    CACHE_MISS_QUEUE_KEY,
    MAX_REBUILDS_PER_WINDOW,
    RATE_LIMIT_KEY_TEMPLATE,
    RATE_LIMIT_WINDOW,
    process_flag_cache_miss_queue,
)


class TestFlagCacheMissQueue(TestCase):
    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_processes_message_from_queue(self, mock_update_task: MagicMock, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        notification = {"team_id": 123, "timestamp": 1234567890}
        mock_redis.llen.return_value = 0  # Queue is empty
        mock_redis.rpop.side_effect = [json.dumps(notification), None]
        mock_redis.incr.return_value = 1

        process_flag_cache_miss_queue()

        self.assertEqual(mock_redis.rpop.call_count, 2)
        mock_redis.incr.assert_called_once_with(RATE_LIMIT_KEY_TEMPLATE.format(team_id=123))
        mock_redis.expire.assert_called_once_with(RATE_LIMIT_KEY_TEMPLATE.format(team_id=123), RATE_LIMIT_WINDOW)
        mock_update_task.assert_called_once_with(123)

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_stops_processing_when_queue_is_empty(
        self, mock_update_task: MagicMock, mock_get_client: MagicMock
    ) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.llen.return_value = 0
        mock_redis.rpop.return_value = None

        process_flag_cache_miss_queue()

        mock_redis.rpop.assert_called_once_with(CACHE_MISS_QUEUE_KEY)
        mock_update_task.assert_not_called()

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_respects_batch_size_limit(self, mock_update_task: MagicMock, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        mock_redis.llen.return_value = BATCH_SIZE + 5
        # Return BATCH_SIZE + 5 messages to ensure we only process BATCH_SIZE
        messages = [json.dumps({"team_id": i, "timestamp": 1234567890}) for i in range(BATCH_SIZE + 5)]
        mock_redis.rpop.side_effect = messages
        mock_redis.incr.return_value = 1

        process_flag_cache_miss_queue()

        # Should only call rpop BATCH_SIZE times (not BATCH_SIZE + 5)
        self.assertEqual(mock_redis.rpop.call_count, BATCH_SIZE)
        self.assertEqual(mock_update_task.call_count, BATCH_SIZE)

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_applies_rate_limiting(self, mock_update_task: MagicMock, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        notification = {"team_id": 456, "timestamp": 1234567890}
        mock_redis.llen.return_value = 1
        mock_redis.rpop.side_effect = [json.dumps(notification), None]
        # Simulate that this is the 3rd rebuild (exceeds limit of 2)
        mock_redis.incr.return_value = MAX_REBUILDS_PER_WINDOW + 1

        process_flag_cache_miss_queue()

        self.assertEqual(mock_redis.rpop.call_count, 2)
        mock_redis.incr.assert_called_once_with(RATE_LIMIT_KEY_TEMPLATE.format(team_id=456))
        # Should NOT dispatch the task because rate limit was exceeded
        mock_update_task.assert_not_called()

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_sets_expiry_on_first_increment(self, mock_update_task: MagicMock, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        notification = {"team_id": 789, "timestamp": 1234567890}
        mock_redis.llen.return_value = 1
        mock_redis.rpop.side_effect = [json.dumps(notification), None]
        # First increment - should set expiry
        mock_redis.incr.return_value = 1

        process_flag_cache_miss_queue()

        mock_redis.expire.assert_called_once_with(RATE_LIMIT_KEY_TEMPLATE.format(team_id=789), RATE_LIMIT_WINDOW)

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_does_not_set_expiry_on_subsequent_increments(
        self, mock_update_task: MagicMock, mock_get_client: MagicMock
    ) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        notification = {"team_id": 999, "timestamp": 1234567890}
        mock_redis.llen.return_value = 1
        mock_redis.rpop.return_value = json.dumps(notification)
        # Second increment - should NOT set expiry
        mock_redis.incr.return_value = 2

        process_flag_cache_miss_queue()

        mock_redis.expire.assert_not_called()

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_handles_malformed_json_gracefully(self, mock_update_task: MagicMock, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # First message is malformed, second is valid
        valid_notification = {"team_id": 111, "timestamp": 1234567890}
        mock_redis.llen.return_value = 2
        mock_redis.rpop.side_effect = ["not valid json", json.dumps(valid_notification), None]
        mock_redis.incr.return_value = 1

        # Should not raise an exception
        process_flag_cache_miss_queue()

        # Should still process the valid message
        mock_update_task.assert_called_once_with(111)

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_handles_missing_team_id_field(self, mock_update_task: MagicMock, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Message missing team_id field
        invalid_notification = {"timestamp": 1234567890}
        valid_notification = {"team_id": 222, "timestamp": 1234567890}
        mock_redis.llen.return_value = 2
        mock_redis.rpop.side_effect = [json.dumps(invalid_notification), json.dumps(valid_notification), None]
        mock_redis.incr.return_value = 1

        # Should not raise an exception
        process_flag_cache_miss_queue()

        # Should still process the valid message
        mock_update_task.assert_called_once_with(222)

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_processes_multiple_teams(self, mock_update_task: MagicMock, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        notifications = [
            json.dumps({"team_id": 100, "timestamp": 1234567890}),
            json.dumps({"team_id": 200, "timestamp": 1234567891}),
            json.dumps({"team_id": 300, "timestamp": 1234567892}),
            None,
        ]
        mock_redis.llen.return_value = 3
        mock_redis.rpop.side_effect = notifications
        mock_redis.incr.return_value = 1

        process_flag_cache_miss_queue()

        # Should process all three teams
        self.assertEqual(mock_update_task.call_count, 3)
        mock_update_task.assert_any_call(100)
        mock_update_task.assert_any_call(200)
        mock_update_task.assert_any_call(300)

    @patch("posthog.tasks.feature_flags.get_client")
    @patch("posthog.tasks.feature_flags.update_team_flags_cache.delay")
    def test_rate_limits_per_team(self, mock_update_task: MagicMock, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Team 100 has 3 messages (should process first 2, skip 3rd)
        # Team 200 has 1 message (should process it)
        notifications = [
            json.dumps({"team_id": 100, "timestamp": 1234567890}),
            json.dumps({"team_id": 100, "timestamp": 1234567891}),
            json.dumps({"team_id": 100, "timestamp": 1234567892}),
            json.dumps({"team_id": 200, "timestamp": 1234567893}),
            None,
        ]
        mock_redis.llen.return_value = 4
        mock_redis.rpop.side_effect = notifications

        # Mock incr to return increasing counts for team 100, but 1 for team 200
        team_100_count = 0

        def incr_with_state(key: str) -> int:
            nonlocal team_100_count
            if "100" in key:
                team_100_count += 1
                return team_100_count
            else:
                return 1

        mock_redis.incr.side_effect = incr_with_state

        process_flag_cache_miss_queue()

        # Should dispatch task for team 100 twice (first two messages)
        # and once for team 200
        self.assertEqual(mock_update_task.call_count, 3)
