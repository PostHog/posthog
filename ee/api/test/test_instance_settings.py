# TODO: Once Clickhouse is moved out of EE, move test cases to posthog/api/test/test_instance_settings.py
from posthog.test.base import ClickhouseTestMixin, snapshot_clickhouse_alter_queries

from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models.instance_setting import get_instance_setting
from posthog.models.performance.sql import PERFORMANCE_EVENT_DATA_TABLE
from posthog.settings.data_stores import CLICKHOUSE_DATABASE

from ee.api.test.base import APILicensedTest


class TestInstanceSettings(ClickhouseTestMixin, APILicensedTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    @snapshot_clickhouse_alter_queries
    def test_update_recordings_performance_events_ttl_setting(self):
        response = self.client.get(f"/api/instance_settings/RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], 3)

        response = self.client.patch(
            f"/api/instance_settings/RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS",
            {"value": 5},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], 5)

        self.assertEqual(get_instance_setting("RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS"), 5)

        table_engine = sync_execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(table)s",
            {"database": CLICKHOUSE_DATABASE, "table": PERFORMANCE_EVENT_DATA_TABLE()},
        )
        self.assertIn("TTL toDate(timestamp) + toIntervalWeek(5)", table_engine[0][0])
