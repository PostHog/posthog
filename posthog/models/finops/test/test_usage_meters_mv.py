"""Produces a meter to the dedicated finops usage-meters Kafka topic and verifies the
finops_usage_meters materialized view lands it with the frozen, typed columns. Guards the
wire contract the emitter (a later PR) depends on: a rename/reorder in the columns constant
or the MV projection, or a wrong column type, would silently drop every produced meter.
Requires a running Kafka broker reachable via settings.KAFKA_PROFILES["default"].
"""

import json
import time

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.conf import settings

from kafka import KafkaProducer

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_FINOPS_USAGE_METERS
from posthog.models.finops.usage_meters import (
    DISTRIBUTED_FINOPS_USAGE_METERS_TABLE_SQL,
    FINOPS_USAGE_METERS_MV,
    FINOPS_USAGE_METERS_MV_SQL,
    FINOPS_USAGE_METERS_TABLE,
    KAFKA_FINOPS_USAGE_METERS_TABLE,
    KAFKA_FINOPS_USAGE_METERS_TABLE_SQL,
    SHARDED_FINOPS_USAGE_METERS_TABLE,
    SHARDED_FINOPS_USAGE_METERS_TABLE_SQL,
    WRITABLE_FINOPS_USAGE_METERS_TABLE,
    WRITABLE_FINOPS_USAGE_METERS_TABLE_SQL,
)

# Far above any seeded test team, so our row stays isolated in the shared dev/test CH.
TEST_TEAM_ID = 9_999_999
TEST_TIMESTAMP = "2026-05-05 12:34:56.000000"


def _wait_for_meter(team_id: int, timeout_seconds: int = 15) -> tuple:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        rows = sync_execute(
            f"""
            SELECT product, team_id, org_id, feature, environment, billable_unit,
                   quantity, system, workload, resource_id, duration_ms, service_name, count
            FROM {FINOPS_USAGE_METERS_TABLE}
            WHERE team_id = %(team_id)s AND billable_unit = 'events'
            """,
            {"team_id": team_id},
        )
        if rows:
            return rows[0]
        time.sleep(0.5)
    raise AssertionError(f"finops_usage_meters never received the produced meter for team {team_id}")


class TestFinopsUsageMetersMV(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        sync_execute(SHARDED_FINOPS_USAGE_METERS_TABLE_SQL())
        sync_execute(DISTRIBUTED_FINOPS_USAGE_METERS_TABLE_SQL())
        sync_execute(WRITABLE_FINOPS_USAGE_METERS_TABLE_SQL())
        sync_execute(KAFKA_FINOPS_USAGE_METERS_TABLE_SQL())
        sync_execute(FINOPS_USAGE_METERS_MV_SQL())
        sync_execute(
            f"DELETE FROM {SHARDED_FINOPS_USAGE_METERS_TABLE} WHERE team_id = %(t)s",
            {"t": TEST_TEAM_ID},
        )
        super().setUp()

    def tearDown(self) -> None:
        sync_execute(f"DROP TABLE IF EXISTS {FINOPS_USAGE_METERS_MV}")
        sync_execute(f"DROP TABLE IF EXISTS {KAFKA_FINOPS_USAGE_METERS_TABLE}")
        sync_execute(f"DROP TABLE IF EXISTS {WRITABLE_FINOPS_USAGE_METERS_TABLE}")
        sync_execute(f"DROP TABLE IF EXISTS {FINOPS_USAGE_METERS_TABLE}")
        sync_execute(f"DROP TABLE IF EXISTS {SHARDED_FINOPS_USAGE_METERS_TABLE} SYNC")
        super().tearDown()

    def test_produced_meter_lands_with_typed_columns(self) -> None:
        producer = KafkaProducer(bootstrap_servers=settings.KAFKA_PROFILES["default"].hosts)
        meter = {
            "timestamp": TEST_TIMESTAMP,
            "product": "ingestion",
            "team_id": TEST_TEAM_ID,
            "org_id": "01890000-0000-0000-0000-000000000000",
            "feature": "",
            "environment": "prod-us",
            "billable_unit": "events",
            "quantity": 1000.0,
            "system": "warpstream",
            "workload": "events-ingestion-consumer",
            "resource_id": "events_plugin_ingestion",
            "duration_ms": 42.5,
            "service_name": "ingestion",
            "count": 3,
        }
        producer.send(topic=KAFKA_CLICKHOUSE_FINOPS_USAGE_METERS, value=json.dumps(meter).encode("utf-8"))
        producer.flush()

        (
            product,
            team_id,
            org_id,
            feature,
            environment,
            billable_unit,
            quantity,
            system,
            workload,
            resource_id,
            duration_ms,
            service_name,
            count,
        ) = _wait_for_meter(TEST_TEAM_ID)

        self.assertEqual(product, "ingestion")
        self.assertEqual(team_id, TEST_TEAM_ID)
        self.assertEqual(org_id, "01890000-0000-0000-0000-000000000000")
        self.assertEqual(feature, "")
        self.assertEqual(environment, "prod-us")
        self.assertEqual(billable_unit, "events")
        self.assertEqual(quantity, 1000.0)
        self.assertEqual(system, "warpstream")
        self.assertEqual(workload, "events-ingestion-consumer")
        self.assertEqual(resource_id, "events_plugin_ingestion")
        self.assertEqual(duration_ms, 42.5)
        self.assertEqual(service_name, "ingestion")
        self.assertEqual(count, 3)
