from typing import Optional

from freezegun.api import freeze_time

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_APP_METRICS
from posthog.models.app_metrics.sql import INSERT_APP_METRICS_SQL
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.queries.app_metrics.app_metrics import AppMetricsQuery
from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.utils import cast_timestamp_or_now


def create_app_metric(
    team_id: int,
    timestamp: str,
    plugin_config_id: int,
    category: str,
    job_id: Optional[str] = None,
    successes=0,
    successes_on_retry=0,
    failures=0,
):
    timestamp = cast_timestamp_or_now(timestamp)
    data = {
        "timestamp": format_clickhouse_timestamp(timestamp),
        "team_id": team_id,
        "plugin_config_id": plugin_config_id,
        "category": category,
        "job_id": job_id or "",
        "successes": successes,
        "successes_on_retry": successes_on_retry,
        "failures": failures,
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_APP_METRICS, sql=INSERT_APP_METRICS_SQL, data=data)


class TestAppMetricsQuery(ClickhouseTestMixin, BaseTest):
    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_app_metrics(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=1,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-03T00:00:00Z",
            successes=3,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-03T00:00:00Z",
            failures=2,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T00:20:00Z",
            successes=10,
            successes_on_retry=5,
        )
        filter = self.make_filter(category="processEvent", date_from="-7d")

        results = AppMetricsQuery(self.team, 3, filter).run()

        self.assertEqual(
            results["dates"],
            [
                "2021-11-28",
                "2021-11-29",
                "2021-11-30",
                "2021-12-01",
                "2021-12-02",
                "2021-12-03",
                "2021-12-04",
                "2021-12-05",
            ],
        )
        self.assertEqual(results["successes"], [0, 0, 0, 0, 0, 3, 0, 10])
        self.assertEqual(results["successes_on_retry"], [0, 0, 0, 0, 0, 0, 0, 5])
        self.assertEqual(results["failures"], [1, 0, 0, 0, 0, 2, 0, 0])
        self.assertEqual(results["totals"], {"successes": 13, "successes_on_retry": 5, "failures": 3})

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_filter_by_job_id(self):
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            job_id="12345",
            timestamp="2021-12-05T00:10:00Z",
            successes_on_retry=2,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            job_id="67890",
            timestamp="2021-12-05T00:20:00Z",
            failures=1,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            timestamp="2021-12-05T00:10:00Z",
            successes=3,
        )
        filter = self.make_filter(category="exportEvents", date_from="-7d", job_id="12345")

        results = AppMetricsQuery(self.team, 3, filter).run()

        self.assertEqual(results["successes_on_retry"], [0, 0, 0, 0, 0, 0, 0, 2])
        self.assertEqual(results["totals"], {"successes": 0, "successes_on_retry": 2, "failures": 0})

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_filter_by_hourly_date_range(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T00:10:00Z",
            successes=2,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            job_id="67890",
            timestamp="2021-12-05T01:20:00Z",
            successes=1,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T02:10:00Z",
            successes=3,
        )
        filter = self.make_filter(category="processEvent", date_from="-13h", date_to="-5h")

        results = AppMetricsQuery(self.team, 3, filter).run()

        self.assertEqual(
            results["dates"],
            [
                "2021-12-05 00:00:00",
                "2021-12-05 01:00:00",
                "2021-12-05 02:00:00",
                "2021-12-05 03:00:00",
                "2021-12-05 04:00:00",
                "2021-12-05 05:00:00",
                "2021-12-05 06:00:00",
                "2021-12-05 07:00:00",
                "2021-12-05 08:00:00",
            ],
        )
        self.assertEqual(results["successes"], [2, 1, 3, 0, 0, 0, 0, 0, 0])
        self.assertEqual(results["totals"], {"successes": 6, "successes_on_retry": 0, "failures": 0})

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_ignores_unrelated_data(self):
        # Positive examples: testing time bounds
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            successes=1,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            successes=2,
        )

        # Negative examples
        # Different team
        create_app_metric(
            team_id=-1, category="processEvent", plugin_config_id=3, timestamp="2021-12-05T13:10:00Z", failures=1
        )
        # Different pluginConfigId
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=-1,
            timestamp="2021-12-05T13:10:00Z",
            failures=2,
        )
        # Different category
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=3,
        )
        # Timestamp out of range
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-27T23:59:59Z",
            failures=4,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-06T00:00:00Z",
            failures=5,
        )

        filter = self.make_filter(category="processEvent", date_from="-7d")

        results = AppMetricsQuery(self.team, 3, filter).run()

        self.assertEqual(results["totals"], {"successes": 3, "successes_on_retry": 0, "failures": 0})

    def make_filter(self, **kwargs) -> AppMetricsRequestSerializer:
        filter = AppMetricsRequestSerializer(data=kwargs)
        filter.is_valid(raise_exception=True)
        return filter
