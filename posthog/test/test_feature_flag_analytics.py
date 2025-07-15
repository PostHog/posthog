from unittest.mock import MagicMock, patch

from freezegun import freeze_time, configure, config  # type: ignore
import pytest
import uuid
from posthog.api.feature_flag import _create_usage_dashboard
from posthog.constants import FlagRequestType
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feature_flag.flag_analytics import (
    capture_usage_for_all_teams,
    find_flags_with_enriched_analytics,
    increment_request_count,
    capture_team_decide_usage,
)
from posthog.models.team.team import Team
from posthog.test.base import BaseTest, QueryMatchingTest, snapshot_postgres_queries_context
from posthog import redis
import datetime
import concurrent.futures
from posthog.test.base import _create_event, flush_persons_and_events


class TestFeatureFlagAnalytics(BaseTest, QueryMatchingTest):
    maxDiff = None

    def tearDown(self):
        configure(default_ignore_list=config.DEFAULT_IGNORE_LIST)
        return super().tearDown()

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
                client.hgetall(f"posthog:decide_requests:{team_id}"),
                {b"165192618": b"10", b"165192619": b"5"},
            )
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{other_team_id}"),
                {b"165192618": b"7", b"165192619": b"3"},
            )
            self.assertEqual(client.hgetall(f"posthog:decide_requests:other"), {})

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_capture_team_decide_usage(self):
        mock_capture = MagicMock()
        team_id = 3
        other_team_id = 1243
        team_uuid = "team-uuid"
        other_team_uuid = "other-team-uuid"

        with (
            freeze_time("2022-05-07 12:23:07") as frozen_datetime,
            self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="token"),
        ):
            for _ in range(10):
                # 10 requests in first bucket
                increment_request_count(team_id)
                increment_request_count(team_id, 1, FlagRequestType.LOCAL_EVALUATION)
            for _ in range(7):
                # 7 requests for other team
                increment_request_count(other_team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=5))

            for _ in range(5):
                # 5 requests in second bucket
                increment_request_count(team_id)
                increment_request_count(team_id, 1, FlagRequestType.LOCAL_EVALUATION)
            for _ in range(3):
                # 3 requests for other team
                increment_request_count(other_team_id)

            frozen_datetime.tick(datetime.timedelta(seconds=10))

            for _ in range(5):
                # 5 requests in third bucket
                increment_request_count(team_id)
                increment_request_count(team_id, 1, FlagRequestType.LOCAL_EVALUATION)
                increment_request_count(other_team_id)

            capture_team_decide_usage(mock_capture, team_id, team_uuid)
            # these other requests should not add duplicate counts
            capture_team_decide_usage(mock_capture, team_id, team_uuid)
            capture_team_decide_usage(mock_capture, team_id, team_uuid)
            assert mock_capture.capture.call_count == 2
            mock_capture.capture.assert_any_call(
                distinct_id=team_id,
                event="decide usage",
                properties={
                    "count": 15,
                    "team_id": team_id,
                    "team_uuid": team_uuid,
                    "max_time": 1651926190,
                    "min_time": 1651926180,
                    "token": "token",
                },
            )
            mock_capture.capture.assert_any_call(
                distinct_id=team_id,
                event="local evaluation usage",
                properties={
                    "count": 15,
                    "team_id": team_id,
                    "team_uuid": team_uuid,
                    "max_time": 1651926190,
                    "min_time": 1651926180,
                    "token": "token",
                },
            )

            mock_capture.reset_mock()
            capture_team_decide_usage(mock_capture, other_team_id, other_team_uuid)
            capture_team_decide_usage(mock_capture, other_team_id, other_team_uuid)
            mock_capture.capture.assert_called_once_with(
                distinct_id=other_team_id,
                event="decide usage",
                properties={
                    "count": 10,
                    "team_id": other_team_id,
                    "team_uuid": other_team_uuid,
                    "max_time": 1651926190,
                    "min_time": 1651926180,
                    "token": "token",
                },
            )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_no_token_loses_capture_team_decide_usage_data(self):
        mock_capture = MagicMock()
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

            capture_team_decide_usage(mock_capture, team_id, team_uuid)
            capture_team_decide_usage(mock_capture, team_id, team_uuid)
            mock_capture.capture.assert_not_called()

            client = redis.get_client()
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{team_id}"),
                {b"165192620": b"5"},
            )

            with self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="token"):
                capture_team_decide_usage(mock_capture, team_id, team_uuid)
                # no data anymore to capture
                mock_capture.capture.assert_not_called()

                mock_capture.reset_mock()

                capture_team_decide_usage(mock_capture, other_team_id, other_team_uuid)
                mock_capture.capture.assert_called_once_with(
                    distinct_id=other_team_id,
                    event="decide usage",
                    properties={
                        "count": 10,
                        "team_id": other_team_id,
                        "team_uuid": other_team_uuid,
                        "max_time": 1651926190,
                        "min_time": 1651926180,
                        "token": "token",
                    },
                )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_efficient_querying_of_team_decide_usage_data(self):
        mock_capture = MagicMock()
        team_id = 3901
        other_team_id = 1243
        # generate uuid
        team_uuid = uuid.uuid4()
        other_team_uuid = uuid.uuid4()

        # make sure the teams exist to query them
        Team.objects.create(id=team_id, organization=self.organization, api_token=f"token:::{team_id}", uuid=team_uuid)

        Team.objects.create(
            id=other_team_id, organization=self.organization, api_token=f"token:::{other_team_id}", uuid=other_team_uuid
        )

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

            with self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="token"), snapshot_postgres_queries_context(self):
                capture_usage_for_all_teams(mock_capture)

                mock_capture.capture.assert_any_call(
                    distinct_id=team_id,
                    event="decide usage",
                    properties={
                        "count": 15,
                        "team_id": team_id,
                        "team_uuid": team_uuid,
                        "max_time": 1651926190,
                        "min_time": 1651926180,
                        "token": "token",
                    },
                )

                mock_capture.capture.assert_any_call(
                    distinct_id=other_team_id,
                    event="decide usage",
                    properties={
                        "count": 10,
                        "team_id": other_team_id,
                        "team_uuid": other_team_uuid,
                        "max_time": 1651926190,
                        "min_time": 1651926180,
                        "token": "token",
                    },
                )
                assert mock_capture.capture.call_count == 2

    @pytest.mark.skip(
        reason="This works locally, but causes issues in CI because the freeze_time applies to threads as well in unrelated tests, causing timeouts."
    )
    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_no_interference_between_different_types_of_new_incoming_increments(self):
        # we want freezetime to apply to threads too.
        # However, the list can't be empty, so we need to add something.
        configure(default_ignore_list=["tensorflow"])

        mock_capture = MagicMock()
        team_id = 3
        other_team_id = 1243
        team_uuid = "team-uuid"

        with (
            freeze_time("2022-05-07 12:23:07") as frozen_datetime,
            self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="token"),
        ):
            for _ in range(10):
                # 10 requests in first bucket
                increment_request_count(team_id)
                increment_request_count(team_id, 1, FlagRequestType.LOCAL_EVALUATION)

            frozen_datetime.tick(datetime.timedelta(seconds=5))

            for _ in range(5):
                # 5 requests in second bucket
                increment_request_count(team_id)
                increment_request_count(team_id, 1, FlagRequestType.LOCAL_EVALUATION)

            frozen_datetime.tick(datetime.timedelta(seconds=10))

            for _ in range(3):
                # 3 requests in third bucket
                increment_request_count(team_id)
                increment_request_count(team_id, 1, FlagRequestType.LOCAL_EVALUATION)

            frozen_datetime.tick(datetime.timedelta(seconds=2))

            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                future_to_index = {executor.submit(increment_request_count, team_id): index for index in range(5, 10)}
                future_to_index = {
                    executor.submit(capture_team_decide_usage, mock_capture, team_id, team_uuid): index
                    for index in range(5)
                }
                future_to_index = {
                    executor.submit(
                        increment_request_count,
                        team_id,
                        1,
                        FlagRequestType.LOCAL_EVALUATION,
                    ): index
                    for index in range(10, 15)
                }

            for future in concurrent.futures.as_completed(future_to_index):
                result = future.result()
                assert result is None
                assert future.exception() is None

            mock_capture.capture.assert_any_call(
                distinct_id=team_id,
                event="decide usage",
                properties={
                    "count": 15,
                    "team_id": team_id,
                    "team_uuid": team_uuid,
                    "max_time": 1651926190,
                    "min_time": 1651926180,
                    "token": "token",
                },
            )
            mock_capture.capture.assert_any_call(
                distinct_id=team_id,
                event="local evaluation usage",
                properties={
                    "count": 15,
                    "team_id": team_id,
                    "team_uuid": team_uuid,
                    "max_time": 1651926190,
                    "min_time": 1651926180,
                    "token": "token",
                },
            )
            assert mock_capture.capture.call_count == 2

            client = redis.get_client()

            # check that the increments made it through
            # and no extra requests were counted
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{team_id}"),
                {b"165192620": b"8"},
            )
            self.assertEqual(
                client.hgetall(f"posthog:local_evaluation_requests:{team_id}"),
                {b"165192620": b"8"},
            )
            self.assertEqual(client.hgetall(f"posthog:decide_requests:{other_team_id}"), {})
            self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{other_team_id}"), {})

    @pytest.mark.skip(
        reason="This works locally, but causes issues in CI because the freeze_time applies to threads as well in unrelated tests, causing timeouts."
    )
    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_locking_works_for_capture_team_decide_usage(self):
        # we want freezetime to apply to threads too.
        # However, the list can't be empty, so we need to add something.
        configure(default_ignore_list=["tensorflow"])

        mock_capture = MagicMock()
        team_id = 3
        other_team_id = 1243
        team_uuid = "team-uuid"
        other_team_uuid = "other-team-uuid"

        with (
            freeze_time("2022-05-07 12:23:07") as frozen_datetime,
            self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="token"),
        ):
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
                    executor.submit(capture_team_decide_usage, mock_capture, team_id, team_uuid): index
                    for index in range(5)
                }
                future_to_index = {
                    executor.submit(
                        capture_team_decide_usage,
                        mock_capture,
                        other_team_id,
                        other_team_uuid,
                    ): index
                    for index in range(5, 10)
                }

            for future in concurrent.futures.as_completed(future_to_index):
                result = future.result()
                assert result is None
                assert future.exception() is None

            mock_capture.capture.assert_any_call(
                distinct_id=team_id,
                event="decide usage",
                properties={
                    "count": 15,
                    "team_id": team_id,
                    "team_uuid": team_uuid,
                    "max_time": 1651926190,
                    "min_time": 1651926180,
                    "token": "token",
                },
            )
            mock_capture.capture.assert_any_call(
                distinct_id=other_team_id,
                event="decide usage",
                properties={
                    "count": 10,
                    "team_id": other_team_id,
                    "team_uuid": other_team_uuid,
                    "max_time": 1651926190,
                    "min_time": 1651926180,
                    "token": "token",
                },
            )
            assert mock_capture.capture.call_count == 2

    # TODO: Figure out a way to run these tests in CI
    @pytest.mark.skip(
        reason="This works locally, but causes issues in CI because the freeze_time applies to threads as well in unrelated tests, causing timeouts."
    )
    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_locking_in_redis_doesnt_block_new_incoming_increments(self):
        # we want freezetime to apply to threads too.
        # However, the list can't be empty, so we need to add something.
        configure(default_ignore_list=["tensorflow"])

        mock_capture = MagicMock()
        team_id = 3
        other_team_id = 1243
        team_uuid = "team-uuid"

        with (
            freeze_time("2022-05-07 12:23:07") as frozen_datetime,
            self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="token"),
        ):
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
                    executor.submit(capture_team_decide_usage, mock_capture, team_id, team_uuid): index
                    for index in range(5)
                }
                future_to_index = {executor.submit(increment_request_count, team_id): index for index in range(5, 10)}

            for future in concurrent.futures.as_completed(future_to_index):
                result = future.result()
                assert result is None
                assert future.exception() is None

            mock_capture.capture.assert_any_call(
                distinct_id=team_id,
                event="decide usage",
                properties={
                    "count": 15,
                    "team_id": team_id,
                    "team_uuid": team_uuid,
                    "max_time": 1651926190,
                    "min_time": 1651926180,
                    "token": "token",
                },
            )
            assert mock_capture.capture.call_count == 1

            client = redis.get_client()

            # check that the increments made it through
            # and no extra requests were counted
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{team_id}"),
                {b"165192620": b"8"},
            )
            self.assertEqual(client.hgetall(f"posthog:decide_requests:{other_team_id}"), {})


class TestEnrichedAnalytics(BaseTest):
    def test_find_flags_with_enriched_analytics(self):
        f1 = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="test_flag",
            created_by=self.user,
            ensure_experience_continuity=False,
        )
        f2 = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        f3 = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature2",
            created_by=self.user,
        )
        f4 = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature3",
            created_by=self.user,
        )

        # create usage dashboard for f1 and f3
        _create_usage_dashboard(f1, self.user)
        _create_usage_dashboard(f3, self.user)

        # create some enriched analytics events
        _create_event(
            team=self.team,
            distinct_id="test",
            event="$feature_view",
            properties={"feature_flag": "test_flag"},
            timestamp="2021-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            distinct_id="test2",
            event="$feature_view",
            properties={"feature_flag": "test_flag"},
            timestamp="2021-01-01T22:05:00Z",
        )
        # out of bounds
        _create_event(
            team=self.team,
            distinct_id="test3",
            event="$feature_view",
            properties={"feature_flag": "test_flag"},
            timestamp="2021-01-12T12:00:10Z",
        )
        # different flag
        _create_event(
            team=self.team,
            distinct_id="test4",
            event="$feature_view",
            properties={"feature_flag": "beta-feature"},
            timestamp="2021-01-01T12:00:00Z",
        )
        # non-existing flag
        _create_event(
            team=self.team,
            distinct_id="test5",
            event="$feature_view",
            properties={"feature_flag": "non-existing-flag"},
            timestamp="2021-01-01T12:10:00Z",
        )
        # incorrect event
        _create_event(
            team=self.team,
            distinct_id="test6",
            event="$pageview",
            properties={"feature_flag": "beta-feature2"},
            timestamp="2021-01-01T12:20:00Z",
        )
        # incorrect property
        _create_event(
            team=self.team,
            distinct_id="test7",
            event="$feature_view",
            properties={"$$feature_flag": "beta-feature3"},
            timestamp="2021-01-01T12:30:00Z",
        )

        flush_persons_and_events()

        start = datetime.datetime(2021, 1, 1, 0, 0, 0)
        end = datetime.datetime(2021, 1, 2, 0, 0, 0)

        find_flags_with_enriched_analytics(start, end)

        f1.refresh_from_db()
        f2.refresh_from_db()
        f3.refresh_from_db()
        f4.refresh_from_db()

        self.assertEqual(f1.has_enriched_analytics, True)
        self.assertEqual(f2.has_enriched_analytics, True)
        self.assertEqual(f3.has_enriched_analytics, False)
        self.assertEqual(f4.has_enriched_analytics, False)

        # now try deleting a usage dashboard. It should not delete the feature flag
        assert f1.usage_dashboard is not None
        self.assertEqual(f1.usage_dashboard.name, "Generated Dashboard: test_flag Usage")
        self.assertEqual(f2.usage_dashboard, None)
        assert f3.usage_dashboard is not None
        self.assertEqual(f3.usage_dashboard.name, "Generated Dashboard: beta-feature2 Usage")
        self.assertEqual(f4.usage_dashboard, None)

        # 1 should have enriched analytics, but nothing else
        self.assertEqual(f1.usage_dashboard_has_enriched_insights, True)
        self.assertEqual(f2.usage_dashboard_has_enriched_insights, False)
        self.assertEqual(f3.usage_dashboard_has_enriched_insights, False)
        self.assertEqual(f4.usage_dashboard_has_enriched_insights, False)

        self.assertEqual(f1.usage_dashboard.tiles.count(), 4)
        self.assertEqual(f3.usage_dashboard.tiles.count(), 2)

        # now try deleting a usage dashboard. It should not delete the feature flag
        f1.usage_dashboard.delete()

        f1.refresh_from_db()
        self.assertEqual(f1.has_enriched_analytics, True)
        self.assertEqual(f1.usage_dashboard, None)
