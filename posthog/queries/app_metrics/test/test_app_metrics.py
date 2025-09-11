import json
from datetime import datetime
from typing import Optional

from freezegun.api import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_APP_METRICS
from posthog.models.app_metrics.sql import INSERT_APP_METRICS_SQL
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.utils import UUIDT
from posthog.queries.app_metrics.app_metrics import (
    AppMetricsErrorDetailsQuery,
    AppMetricsErrorsQuery,
    AppMetricsQuery,
    TeamPluginsDeliveryRateQuery,
)
from posthog.queries.app_metrics.serializers import AppMetricsErrorsRequestSerializer, AppMetricsRequestSerializer
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
    error_uuid: Optional[str] = None,
    error_type: Optional[str] = None,
    error_details: Optional[dict] = None,
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
        "error_uuid": error_uuid or "00000000-0000-0000-0000-000000000000",
        "error_type": error_type or "",
        "error_details": json.dumps(error_details) if error_details else "",
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_APP_METRICS, sql=INSERT_APP_METRICS_SQL, data=data)


def make_filter(serializer_klass=AppMetricsRequestSerializer, **kwargs) -> AppMetricsRequestSerializer:
    filter = serializer_klass(data=kwargs)
    filter.is_valid(raise_exception=True)
    return filter


class TestTeamPluginsDeliveryRateQuery(ClickhouseTestMixin, BaseTest):
    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_query_delivery_rate(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=1,
            timestamp="2021-12-05T00:10:00Z",
            failures=1,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=2,
            timestamp="2021-12-05T00:10:00Z",
            successes=5,
            failures=5,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T00:10:00Z",
            successes=5,
            successes_on_retry=15,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=4,
            timestamp="2021-12-05T00:10:00Z",
            successes=0,  # handles all zero rows
            successes_on_retry=0,
            failures=0,
        )

        results = TeamPluginsDeliveryRateQuery(self.team).run()
        self.assertEqual(results, {1: 0, 2: 0.5, 3: 1, 4: 1})

    @freeze_time("2021-12-05T13:23:00Z")
    def test_ignores_out_of_bound_metrics(self):
        create_app_metric(
            team_id=-1,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T00:10:00Z",
            successes=5,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=1,
            timestamp="2021-12-04T00:10:00Z",
            failures=1,
        )
        results = TeamPluginsDeliveryRateQuery(self.team).run()
        self.assertEqual(results, {})


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
        filter = make_filter(category="processEvent", date_from="-7d")

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
        filter = make_filter(category="exportEvents", date_from="-7d", job_id="12345")

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
        filter = make_filter(category="processEvent", date_from="-13h", date_to="-5h")

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
            team_id=-1,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=1,
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

        filter = make_filter(category="processEvent", date_from="-7d")

        results = AppMetricsQuery(self.team, 3, filter).run()

        self.assertEqual(results["totals"], {"successes": 3, "successes_on_retry": 0, "failures": 0})

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_composeWebhook_sums_all_failures_but_only_webhook_successes(self):
        # Positive examples: testing time bounds
        create_app_metric(
            team_id=self.team.pk,
            category="composeWebhook",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            successes=1,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="composeWebhook",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            successes=2,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="webhook",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            successes=10,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="webhook",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            successes=20,
        )
        # add failures
        create_app_metric(
            team_id=self.team.pk,
            category="composeWebhook",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=100,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="composeWebhook",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=200,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="webhook",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=1000,
        )
        create_app_metric(
            team_id=self.team.pk,
            category="webhook",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=2000,
        )

        filter = make_filter(date_from="-7d")

        results = AppMetricsQuery(self.team, 3, filter).run()

        self.assertEqual(results["totals"], {"successes": 30, "successes_on_retry": 0, "failures": 3300})


class TestAppMetricsErrorsQuery(ClickhouseTestMixin, BaseTest):
    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_errors_query(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="SomeError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-03T00:00:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-03T00:00:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T00:20:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )

        filter = make_filter(category="processEvent", date_from="-7d")
        results = AppMetricsErrorsQuery(self.team, 3, filter).run()

        self.assertEqual(
            results,
            [
                {
                    "error_type": "AnotherError",
                    "count": 3,
                    "last_seen": datetime.fromisoformat("2021-12-05T00:20:00+00:00"),
                },
                {
                    "error_type": "SomeError",
                    "count": 1,
                    "last_seen": datetime.fromisoformat("2021-11-28T00:10:00+00:00"),
                },
            ],
        )

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_errors_query_filter_by_job_id(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="SomeError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            job_id="1234",
            timestamp="2021-12-03T00:00:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            job_id="1234",
            timestamp="2021-12-03T00:00:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            job_id="5678",
            timestamp="2021-12-05T00:20:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )

        filter = make_filter(category="processEvent", date_from="-7d", job_id="1234")
        results = AppMetricsErrorsQuery(self.team, 3, filter).run()

        self.assertEqual(
            results,
            [
                {
                    "error_type": "AnotherError",
                    "count": 2,
                    "last_seen": datetime.fromisoformat("2021-12-03T00:00:00+00:00"),
                },
            ],
        )

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_ignores_unrelated_data(self):
        # Positive examples: testing time bounds
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="RelevantError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="RelevantError",
        )

        # Negative examples
        # Different team
        create_app_metric(
            team_id=-1,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )
        # Different pluginConfigId
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=-1,
            timestamp="2021-12-05T13:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )
        # Different category
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )
        # Timestamp out of range
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-27T23:59:59Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-06T00:00:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="AnotherError",
        )

        filter = make_filter(category="processEvent", date_from="-7d")
        results = AppMetricsErrorsQuery(self.team, 3, filter).run()

        self.assertEqual(
            results,
            [
                {
                    "error_type": "RelevantError",
                    "count": 2,
                    "last_seen": datetime.fromisoformat("2021-12-05T13:10:00+00:00"),
                },
            ],
        )


class TestAppMetricsErrorDetailsQuery(ClickhouseTestMixin, BaseTest):
    UUIDS = [UUIDT() for _ in range(2)]

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_error_details_query(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=1,
            error_uuid=str(self.UUIDS[0]),
            error_type="SomeError",
            error_details={"event": {}},
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T00:10:00Z",
            failures=1,
            error_uuid=str(self.UUIDS[1]),
            error_type="SomeError",
            error_details={"event": {}},
        )

        filter = make_filter(
            serializer_klass=AppMetricsErrorsRequestSerializer,
            category="processEvent",
            error_type="SomeError",
        )
        results = AppMetricsErrorDetailsQuery(self.team, 3, filter).run()

        self.assertEqual(
            results,
            [
                {
                    "timestamp": datetime.fromisoformat("2021-12-05T00:10:00+00:00"),
                    "error_uuid": self.UUIDS[1],
                    "error_type": "SomeError",
                    "error_details": {"event": {}},
                },
                {
                    "timestamp": datetime.fromisoformat("2021-11-28T00:10:00+00:00"),
                    "error_uuid": self.UUIDS[0],
                    "error_type": "SomeError",
                    "error_details": {"event": {}},
                },
            ],
        )

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_error_details_query_filter_by_job_id(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            job_id="1234",
            failures=1,
            error_uuid=str(self.UUIDS[0]),
            error_type="SomeError",
            error_details={"event": {}},
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:20:00Z",
            job_id="5678",
            failures=1,
            error_uuid=str(self.UUIDS[0]),
            error_type="SomeError",
            error_details={"event": {}},
        )
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:30:00Z",
            failures=1,
            error_uuid=str(self.UUIDS[0]),
            error_type="SomeError",
            error_details={"event": {}},
        )

        filter = make_filter(
            serializer_klass=AppMetricsErrorsRequestSerializer,
            category="processEvent",
            error_type="SomeError",
            job_id="1234",
        )
        results = AppMetricsErrorDetailsQuery(self.team, 3, filter).run()

        self.assertEqual(
            results,
            [
                {
                    "timestamp": datetime.fromisoformat("2021-11-28T00:10:00+00:00"),
                    "error_uuid": self.UUIDS[0],
                    "error_type": "SomeError",
                    "error_details": {"event": {}},
                }
            ],
        )

    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_ignores_unrelated_data(self):
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=1,
            error_uuid=str(self.UUIDS[0]),
            error_type="SomeError",
            error_details={"event": {}},
        )

        # Different team
        create_app_metric(
            team_id=-1,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="SomeError",
        )
        # Different pluginConfigId
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=-1,
            timestamp="2021-12-05T13:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="SomeError",
        )
        # Different category
        create_app_metric(
            team_id=self.team.pk,
            category="exportEvents",
            plugin_config_id=3,
            timestamp="2021-12-05T13:10:00Z",
            failures=1,
            error_uuid=str(UUIDT()),
            error_type="SomeError",
        )
        # Different error_type
        create_app_metric(
            team_id=self.team.pk,
            category="processEvent",
            plugin_config_id=3,
            timestamp="2021-11-28T00:10:00Z",
            failures=1,
            error_uuid=str(self.UUIDS[0]),
            error_type="AnotherError",
            error_details={"event": {}},
        )

        filter = make_filter(
            serializer_klass=AppMetricsErrorsRequestSerializer,
            category="processEvent",
            error_type="SomeError",
        )
        results = AppMetricsErrorDetailsQuery(self.team, 3, filter).run()

        self.assertEqual(
            results,
            [
                {
                    "timestamp": datetime.fromisoformat("2021-11-28T00:10:00+00:00"),
                    "error_uuid": self.UUIDS[0],
                    "error_type": "SomeError",
                    "error_details": {"event": {}},
                }
            ],
        )
