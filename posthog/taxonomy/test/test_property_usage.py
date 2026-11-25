from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.utils.event_usage import PROPERTY_USAGE_APP_SOURCE
from posthog.models import Team
from posthog.taxonomy.property_usage import (
    USAGE_MAP_STALE_AFTER,
    fetch_property_usage_map,
    get_property_usage_map,
    rebuild_property_usage_map_in_background,
)
from posthog.test.fixtures import create_app_metric2


class TestFetchPropertyUsageMap(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # app_metrics2 keeps rows across tests, so each test logs to a team of its own.
        self.team = Team.objects.create(organization=self.organization)

    def _log(self, instance_id: str, days_ago: float, count: int = 1, metric_name: str = "viewed") -> None:
        create_app_metric2(
            team_id=self.team.pk,
            app_source=PROPERTY_USAGE_APP_SOURCE,
            app_source_id="",
            instance_id=instance_id,
            metric_kind="usage",
            metric_name=metric_name,
            count=count,
            timestamp=datetime.now(UTC) - timedelta(days=days_ago),
        )

    @parameterized.expand(
        [
            ("tracking_started_inside_the_window", False, 10),
            ("tracking_started_before_the_window", True, None),
        ]
    )
    def test_counts_the_last_30_days_and_reports_a_partial_window(
        self, _name: str, logged_before_window: bool, expected_tracking_days_ago: int | None
    ) -> None:
        self._log("property:event:$browser", days_ago=2, count=2)
        self._log("property:event:$browser", days_ago=10)
        self._log("property:group:0:industry", days_ago=5, count=4)
        self._log("property:event:$browser", days_ago=3, metric_name="other")
        create_app_metric2(
            team_id=self.team.pk + 1_000_000,
            app_source=PROPERTY_USAGE_APP_SOURCE,
            instance_id="property:event:$browser",
            metric_name="viewed",
            count=100,
        )
        if logged_before_window:
            self._log("property:event:plan", days_ago=30.5, count=9)

        usage_map = fetch_property_usage_map(self.team, Workload.ONLINE)

        assert dict(usage_map.counts) == {"property:event:$browser": 3, "property:group:0:industry": 4}
        if expected_tracking_days_ago is None:
            assert usage_map.tracking_since is None
        else:
            assert usage_map.tracking_since is not None
            expected = datetime.now(UTC) - timedelta(days=expected_tracking_days_ago)
            assert abs(usage_map.tracking_since - expected) < timedelta(hours=1)


class TestGetPropertyUsageMap(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @patch("posthog.taxonomy.property_usage.refresh_property_usage_map.delay")
    @patch("posthog.taxonomy.property_usage.sync_execute")
    def test_serves_a_stale_map_and_queues_one_rebuild(self, mock_sync_execute, mock_delay) -> None:
        first_seen = datetime(2026, 10, 1, tzinfo=UTC)
        mock_sync_execute.return_value = [("property:event:$browser", 3, first_seen)]
        with time_machine.travel(datetime(2026, 11, 1, 12, 0, tzinfo=UTC), tick=False) as traveller:
            built = get_property_usage_map(self.team)
            assert built.count_for("event", "$browser") == 3
            assert mock_sync_execute.call_count == 1

            mock_sync_execute.return_value = [("property:event:$browser", 8, first_seen)]
            assert get_property_usage_map(self.team) == built
            mock_delay.assert_not_called()

            traveller.shift(USAGE_MAP_STALE_AFTER + timedelta(minutes=1))
            assert get_property_usage_map(self.team) == built
            assert get_property_usage_map(self.team) == built
            mock_delay.assert_called_once_with(self.team.pk)
            assert mock_sync_execute.call_count == 1

            rebuild_property_usage_map_in_background(self.team.pk)
            assert get_property_usage_map(self.team).count_for("event", "$browser") == 8

            traveller.shift(USAGE_MAP_STALE_AFTER + timedelta(minutes=1))
            get_property_usage_map(self.team)
            assert mock_delay.call_count == 2
