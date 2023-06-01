from unittest.mock import patch

from freezegun import freeze_time, configure  # type: ignore
from posthog.models.feature_flag.flag_analytics import increment_request_count, capture_team_decide_usage
from posthog.test.base import BaseTest
from posthog import redis
import datetime
import concurrent.futures

# we want freezetime to apply to threads too.
# However, the list can't be empty, so we need to add something.
configure(default_ignore_list=["tensorflow"])


class TestFeatureFlagAnalytics(BaseTest):
    maxDiff = None

    def setUp(self):
        # delete all keys in redis
        r = redis.get_client()
        for key in r.scan_iter("*"):
            r.delete(key)
        return super().setUp()

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_increment_request_count_adds_requests_to_appropriate_buckets(self):
        team_id = 3
        other_team_id = 1243

        with freeze_time("2022-05-07 12:23:07") as frozen_datetime:
            for _ in range(10):
                # 10 requests in first bucket
                increment_request_count(team_id)
            for _ in range(7):
                # 7 requests for other team
                increment_request_count(other_team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=5))

            for _ in range(5):
                # 5 requests in second bucket
                increment_request_count(team_id)
            for _ in range(3):
                # 3 requests for other team
                increment_request_count(other_team_id)

            client = redis.get_client()

            # redis returns encoded bytes
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{team_id}"), {b"165192618": b"10", b"165192619": b"5"}
            )
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{other_team_id}"), {b"165192618": b"7", b"165192619": b"3"}
            )
            self.assertEqual(client.hgetall(f"posthog:decide_requests:other"), {})

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    @patch("posthog.models.feature_flag.flag_analytics.posthoganalytics.capture")
    def test_capture_team_decide_usage(self, mock_capture):
        team_id = 3
        other_team_id = 1243
        team_uuid = "team-uuid"
        other_team_uuid = "other-team-uuid"

        with freeze_time("2022-05-07 12:23:07") as frozen_datetime:
            for _ in range(10):
                # 10 requests in first bucket
                increment_request_count(team_id)
            for _ in range(7):
                # 7 requests for other team
                increment_request_count(other_team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=5))

            for _ in range(5):
                # 5 requests in second bucket
                increment_request_count(team_id)
            for _ in range(3):
                # 3 requests for other team
                increment_request_count(other_team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=10))

            for _ in range(5):
                # 5 requests in third bucket
                increment_request_count(team_id)
                increment_request_count(other_team_id)

            capture_team_decide_usage(team_id, team_uuid)
            # these other requests should not add duplicate counts
            capture_team_decide_usage(team_id, team_uuid)
            capture_team_decide_usage(team_id, team_uuid)
            mock_capture.assert_called_once_with(
                team_uuid, "decide usage", {"count": 15, "team_id": team_id, "team_uuid": team_uuid}
            )

            mock_capture.reset_mock()
            capture_team_decide_usage(other_team_id, other_team_uuid)
            capture_team_decide_usage(other_team_id, other_team_uuid)
            mock_capture.assert_called_once_with(
                other_team_uuid, "decide usage", {"count": 10, "team_id": other_team_id, "team_uuid": other_team_uuid}
            )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    @patch("posthog.models.feature_flag.flag_analytics.posthoganalytics.capture")
    def test_locking_works_for_capture_team_decide_usage(self, mock_capture):
        team_id = 3
        other_team_id = 1243
        team_uuid = "team-uuid"
        other_team_uuid = "other-team-uuid"

        with freeze_time("2022-05-07 12:23:07") as frozen_datetime:
            for _ in range(10):
                # 10 requests in first bucket
                increment_request_count(team_id)
            for _ in range(7):
                # 7 requests for other team
                increment_request_count(other_team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=5))

            for _ in range(5):
                # 5 requests in second bucket
                increment_request_count(team_id)
            for _ in range(3):
                # 3 requests for other team
                increment_request_count(other_team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=10))

            for _ in range(5):
                # 5 requests in third bucket
                increment_request_count(team_id)
                increment_request_count(other_team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=10))

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_index = {
                    executor.submit(capture_team_decide_usage, team_id, team_uuid): index for index in range(5)
                }
                future_to_index = {
                    executor.submit(capture_team_decide_usage, other_team_id, other_team_uuid): index
                    for index in range(5, 10)
                }

            for future in concurrent.futures.as_completed(future_to_index):
                result = future.result()
                assert result is None
                assert future.exception() is None

            mock_capture.assert_any_call(
                team_uuid, "decide usage", {"count": 15, "team_id": team_id, "team_uuid": team_uuid}
            )
            mock_capture.assert_any_call(
                other_team_uuid, "decide usage", {"count": 10, "team_id": other_team_id, "team_uuid": other_team_uuid}
            )
            assert mock_capture.call_count == 2

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    @patch("posthog.models.feature_flag.flag_analytics.posthoganalytics.capture")
    def test_locking_in_redis_doesnt_block_new_incoming_increments(self, mock_capture):
        team_id = 3
        other_team_id = 1243
        team_uuid = "team-uuid"

        with freeze_time("2022-05-07 12:23:07") as frozen_datetime:
            for _ in range(10):
                # 10 requests in first bucket
                increment_request_count(team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=5))

            for _ in range(5):
                # 5 requests in second bucket
                increment_request_count(team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=10))

            for _ in range(3):
                # 3 requests in third bucket
                increment_request_count(team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=2))

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_index = {
                    executor.submit(capture_team_decide_usage, team_id, team_uuid): index for index in range(5)
                }
                future_to_index = {executor.submit(increment_request_count, team_id): index for index in range(5, 10)}

            for future in concurrent.futures.as_completed(future_to_index):
                result = future.result()
                assert result is None
                assert future.exception() is None

            mock_capture.assert_any_call(
                team_uuid, "decide usage", {"count": 15, "team_id": team_id, "team_uuid": team_uuid}
            )
            assert mock_capture.call_count == 1

            client = redis.get_client()

            # check that the increments made it through
            # and no extra requests were counted
            self.assertEqual(client.hgetall(f"posthog:decide_requests:{team_id}"), {b"165192620": b"8"})
            self.assertEqual(client.hgetall(f"posthog:decide_requests:{other_team_id}"), {})
