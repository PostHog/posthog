import datetime

import time_machine
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_flag_evaluations,
    flush_persons_and_events,
)
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog import redis
from posthog.constants import FlagRequestType
from posthog.errors import CHQueryErrorUnknownTable
from posthog.helpers.dashboard_templates import (
    FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME,
    FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME,
)
from posthog.tasks.tasks import find_flags_with_enriched_analytics as find_flags_with_enriched_analytics_task

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.flag_analytics import (
    SDK_LIBRARIES,
    _enriched_flag_key_expr_sql,
    _flag_key_filter_sql,
    find_flags_with_enriched_analytics,
    get_cached_evaluations_7d_by_team,
    get_evaluations_7d_by_team,
    get_team_request_library_key,
    increment_request_count,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig
from products.feature_flags.backend.test.usage_dashboard_fixtures import create_usage_dashboard


class TestFeatureFlagAnalytics(BaseTest, QueryMatchingTest):
    maxDiff = None

    def setUp(self):
        # delete all keys in redis
        r = redis.get_client()
        for key in r.scan_iter("*"):
            r.delete(key)
        return super().setUp()

    @patch("products.feature_flags.backend.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_increment_request_count_adds_requests_to_appropriate_buckets(self):
        team_id = 3
        other_team_id = 1243

        with time_machine.travel("2022-05-07 12:23:07", tick=False) as frozen_datetime:
            for _ in range(10):
                # 10 requests in first bucket
                increment_request_count(team_id)
            for _ in range(7):
                # 7 requests for other team
                increment_request_count(other_team_id)

            frozen_datetime.shift(datetime.timedelta(seconds=5))

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

    @patch("products.feature_flags.backend.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_increment_request_count_remote_config_uses_own_bucket(self):
        team_id = 3

        with time_machine.travel("2022-05-07 12:23:07", tick=False):
            for _ in range(4):
                increment_request_count(team_id)
            for _ in range(6):
                increment_request_count(team_id, 1, FlagRequestType.REMOTE_CONFIG)

            client = redis.get_client()

            # Remote config fetches are telemetry-only, so they must never leak into the
            # decide bucket that billing consumes.
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{team_id}"),
                {b"165192618": b"4"},
            )
            self.assertEqual(
                client.hgetall(f"posthog:remote_config_requests:{team_id}"),
                {b"165192618": b"6"},
            )


class TestSdkBreakdown(BaseTest):
    def setUp(self):
        r = redis.get_client()
        for key in r.scan_iter("*"):
            r.delete(key)
        return super().setUp()

    def test_get_team_request_library_key_decide(self):
        self.assertEqual(
            get_team_request_library_key(123, FlagRequestType.DECIDE, "posthog-js"),
            "posthog:decide_requests:sdk:123:posthog-js",
        )
        self.assertEqual(
            get_team_request_library_key(456, FlagRequestType.DECIDE, "posthog-node"),
            "posthog:decide_requests:sdk:456:posthog-node",
        )

    def test_get_team_request_library_key_local_evaluation(self):
        self.assertEqual(
            get_team_request_library_key(123, FlagRequestType.LOCAL_EVALUATION, "posthog-python"),
            "posthog:local_evaluation_requests:sdk:123:posthog-python",
        )

    def test_sdk_libraries_matches_rust_library_enum(self):
        """
        Verify SDK_LIBRARIES matches Rust Library::as_str() values.

        IMPORTANT: These values must match the Rust Library enum in:
        rust/feature-flags/src/handler/types.rs

        If this test fails after adding a new SDK to Rust, update SDK_LIBRARIES
        in products/feature_flags/backend/flag_analytics.py to match.
        """
        expected_libraries = [
            "posthog-js",
            "posthog-node",
            "posthog-node-mcp",
            "posthog-edge",
            "posthog-convex",
            "posthog-python",
            "posthog-python-mcp",
            "posthog-php",
            "posthog-ruby",
            "posthog-rails",
            "posthog-go",
            "posthog-java",
            "posthog-dotnet",
            "posthog-aspnetcore",
            "posthog-elixir",
            "posthog-rs",
            "posthog-android",
            "posthog-ios",
            "posthog-react-native",
            "posthog-flutter",
            "posthog-kmp",
            "posthog-unity",
            "posthog-server",
            "other",
        ]
        self.assertEqual(SDK_LIBRARIES, expected_libraries)


class TestEnrichedAnalytics(BaseTest):
    def test_find_flags_with_enriched_analytics(self):
        f1 = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="test_flag",
            created_by=self.user,
            ensure_experience_continuity=False,
        )
        f2 = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        f3 = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature2",
            created_by=self.user,
        )
        f4 = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature3",
            created_by=self.user,
        )
        f5 = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature4",
            created_by=self.user,
        )

        # create usage dashboard for f1 and f3
        create_usage_dashboard(f1, self.user)
        create_usage_dashboard(f3, self.user)

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
        # out of bounds for f5 - should not set has_enriched_analytics
        _create_event(
            team=self.team,
            distinct_id="test8",
            event="$feature_view",
            properties={"feature_flag": "beta-feature4"},
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
        f5.refresh_from_db()

        self.assertEqual(f1.has_enriched_analytics, True)
        self.assertEqual(f2.has_enriched_analytics, True)
        self.assertEqual(f3.has_enriched_analytics, False)
        self.assertEqual(f4.has_enriched_analytics, False)
        self.assertEqual(f5.has_enriched_analytics, False)

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

        enriched_insights = {
            tile.insight.name: (
                {series["event"] for series in tile.insight.query["source"]["series"]},
                tile.insight.query["source"]["properties"]["values"][0]["values"][0],
            )
            for tile in f1.usage_dashboard.tiles.select_related("insight")
            if tile.insight
            and tile.insight.query
            and tile.insight.name
            in (FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME, FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME)
        }
        self.assertEqual(
            {
                name: (events, flag_filter["key"], flag_filter["value"])
                for name, (events, flag_filter) in enriched_insights.items()
            },
            {
                FEATURE_FLAG_ENRICHED_VIEW_INSIGHT_NAME: ({"$feature_view"}, "feature_flag", "test_flag"),
                FEATURE_FLAG_ENRICHED_INTERACTION_INSIGHT_NAME: ({"$feature_interaction"}, "feature_flag", "test_flag"),
            },
        )

        # now try deleting a usage dashboard. It should not delete the feature flag
        f1.usage_dashboard.delete()

        f1.refresh_from_db()
        self.assertEqual(f1.has_enriched_analytics, True)
        self.assertEqual(f1.usage_dashboard, None)

    def test_find_flags_with_enriched_analytics_via_feature_interaction_only(self):
        # A flag that only ever receives $feature_interaction (no $feature_view) should still be
        # detected as enriched, since the generated usage dashboard charts both events.
        flag = FeatureFlag.objects.create(
            team=self.team,
            name="Interaction only feature",
            key="interaction-only-flag",
            created_by=self.user,
        )

        _create_event(
            team=self.team,
            distinct_id="test",
            event="$feature_interaction",
            properties={"feature_flag": "interaction-only-flag"},
            timestamp="2021-01-01T12:00:00Z",
        )

        flush_persons_and_events()

        start = datetime.datetime(2021, 1, 1, 0, 0, 0)
        end = datetime.datetime(2021, 1, 2, 0, 0, 0)

        find_flags_with_enriched_analytics(start, end)

        flag.refresh_from_db()
        self.assertEqual(flag.has_enriched_analytics, True)


class TestFindFlagsWithEnrichedAnalyticsTask(SimpleTestCase):
    @patch("products.feature_flags.backend.flag_analytics.find_flags_with_enriched_analytics")
    def test_logs_and_captures_on_failure_without_reraising(self, mock_find_flags: MagicMock) -> None:
        mock_find_flags.side_effect = Exception("boom")

        with patch("posthog.tasks.tasks.capture_exception") as mock_capture:
            find_flags_with_enriched_analytics_task()

        mock_capture.assert_called_once()

    @patch("products.feature_flags.backend.flag_analytics.find_flags_with_enriched_analytics")
    def test_unknown_table_error_is_not_captured(self, mock_find_flags: MagicMock) -> None:
        mock_find_flags.side_effect = CHQueryErrorUnknownTable("Table default.events doesn't exist", code=60)

        with patch("posthog.tasks.tasks.capture_exception") as mock_capture:
            find_flags_with_enriched_analytics_task()

        mock_capture.assert_not_called()


class TestCrossProjectEvaluations(ClickhouseTestMixin, APIBaseTest):
    def test_returns_zero_when_no_events(self):
        counts = get_evaluations_7d_by_team("some_key", [self.team.id], from_flag_evaluations=False)
        assert counts == {self.team.id: 0}

    @parameterized.expand([("events", False, 2, 1), ("flag_evaluations", True, 1, 3)])
    def test_counts_flag_calls_by_team_from_the_selected_table(
        self, _name, from_flag_evaluations, team_count, other_team_count
    ):
        other_team = self.organization.teams.create(name="Other")
        _create_event(
            team=self.team,
            distinct_id="u1",
            event="$feature_flag_called",
            properties={"$feature_flag": "my_flag", "$feature_flag_response": True},
        )
        _create_event(
            team=self.team,
            distinct_id="u2",
            event="$feature_flag_called",
            properties={"$feature_flag": "my_flag", "$feature_flag_response": False},
        )
        _create_event(
            team=other_team,
            distinct_id="u3",
            event="$feature_flag_called",
            properties={"$feature_flag": "my_flag", "$feature_flag_response": True},
        )
        _create_event(
            team=self.team,
            distinct_id="u4",
            event="$feature_flag_called",
            properties={"$feature_flag": "unrelated", "$feature_flag_response": True},
        )
        flush_persons_and_events()

        _create_flag_evaluations(self.team.id, "my_flag")
        _create_flag_evaluations(other_team.id, "my_flag", count=3)
        _create_flag_evaluations(self.team.id, "unrelated")
        _create_flag_evaluations(
            self.team.id, "my_flag", timestamp=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=8)
        )

        counts = get_evaluations_7d_by_team(
            "my_flag", [self.team.id, other_team.id], from_flag_evaluations=from_flag_evaluations
        )

        assert counts == {self.team.id: team_count, other_team.id: other_team_count}

    def test_returns_empty_dict_when_no_team_ids(self):
        assert get_evaluations_7d_by_team("any_flag", [], from_flag_evaluations=False) == {}

    def test_returns_none_when_clickhouse_fails(self):
        with patch(
            "products.feature_flags.backend.flag_analytics.sync_execute",
            side_effect=RuntimeError("boom"),
        ):
            assert get_evaluations_7d_by_team("my_flag", [self.team.id, 99], from_flag_evaluations=False) is None


class TestCachedCrossProjectEvaluations(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_cached_returns_same_result_on_second_call(self):
        with patch(
            "products.feature_flags.backend.flag_analytics.get_evaluations_7d_by_team",
            return_value={self.team.id: 5},
        ) as spy:
            first = get_cached_evaluations_7d_by_team("my_flag", [self.team.id], self.organization.id)
            second = get_cached_evaluations_7d_by_team("my_flag", [self.team.id], self.organization.id)

        assert first == {self.team.id: 5}
        assert second == {self.team.id: 5}
        assert spy.call_count == 1

    def test_failure_results_are_not_cached(self):
        with patch(
            "products.feature_flags.backend.flag_analytics.get_evaluations_7d_by_team",
            side_effect=[None, {self.team.id: 7}],
        ) as spy:
            first = get_cached_evaluations_7d_by_team("my_flag", [self.team.id], self.organization.id)
            second = get_cached_evaluations_7d_by_team("my_flag", [self.team.id], self.organization.id)

        assert first is None
        assert second == {self.team.id: 7}
        assert spy.call_count == 2

    def test_cached_returns_empty_dict_when_no_team_ids(self):
        assert get_cached_evaluations_7d_by_team("any_flag", [], self.organization.id) == {}

    def test_mode_change_does_not_serve_the_result_cached_under_the_previous_mode(self):
        _create_event(
            team=self.team,
            distinct_id="u1",
            event="$feature_flag_called",
            properties={"$feature_flag": "my_flag", "$feature_flag_response": True},
        )
        flush_persons_and_events()
        _create_flag_evaluations(self.team.id, "my_flag", count=2)
        assert get_cached_evaluations_7d_by_team("my_flag", [self.team.id], self.organization.id) == {self.team.id: 1}

        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).update(
            flag_evaluations_mode=FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
        )
        counts = get_cached_evaluations_7d_by_team("my_flag", [self.team.id], self.organization.id)

        assert counts == {self.team.id: 2}


class TestFlagKeyFilterSQL(SimpleTestCase):
    def test_falls_back_to_json_extract_when_not_materialized(self):
        with patch(
            "products.feature_flags.backend.flag_analytics.get_materialized_column_for_property",
            return_value=None,
        ):
            sql = _flag_key_filter_sql()
        assert "JSONExtractString(properties, '$feature_flag')" in sql

    def test_uses_escaped_materialized_column_when_available(self):
        fake_column = MagicMock()
        fake_column.name = "mat_$feature_flag"
        with patch(
            "products.feature_flags.backend.flag_analytics.get_materialized_column_for_property",
            return_value=fake_column,
        ):
            sql = _flag_key_filter_sql()
        assert "`mat_$feature_flag` = %(flag_key)s" in sql
        assert "JSONExtractString" not in sql


class TestEnrichedFlagKeyExprSQL(SimpleTestCase):
    def test_falls_back_to_json_extract_when_not_materialized(self):
        with patch(
            "products.feature_flags.backend.flag_analytics.get_materialized_column_for_property",
            return_value=None,
        ):
            sql = _enriched_flag_key_expr_sql()
        assert sql == "JSONExtractString(properties, 'feature_flag')"

    def test_uses_escaped_materialized_column_when_available(self):
        fake_column = MagicMock()
        fake_column.name = "mat_feature_flag"
        fake_column.is_nullable = False
        with patch(
            "products.feature_flags.backend.flag_analytics.get_materialized_column_for_property",
            return_value=fake_column,
        ):
            sql = _enriched_flag_key_expr_sql()
        assert sql == "`mat_feature_flag`"

    def test_coalesces_nullable_materialized_column(self):
        fake_column = MagicMock()
        fake_column.name = "mat_feature_flag"
        fake_column.is_nullable = True
        with patch(
            "products.feature_flags.backend.flag_analytics.get_materialized_column_for_property",
            return_value=fake_column,
        ):
            sql = _enriched_flag_key_expr_sql()
        assert sql == "ifNull(`mat_feature_flag`, '')"
