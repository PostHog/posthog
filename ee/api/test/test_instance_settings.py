# TODO: Once Clickhouse is moved out of EE, move test cases to posthog/api/test/test_instance_settings.py
from rest_framework import status

from ee.api.test.base import APILicensedTest
from posthog.client import sync_execute
from posthog.models.instance_setting import get_instance_setting
from posthog.models.session_recording_event.sql import SESSION_RECORDING_EVENTS_DATA_TABLE
from posthog.settings.data_stores import CLICKHOUSE_DATABASE
from posthog.test.base import ClickhouseTestMixin, snapshot_clickhouse_alter_queries


class TestInstanceSettings(ClickhouseTestMixin, APILicensedTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    @snapshot_clickhouse_alter_queries
    def test_update_recordings_ttl_setting(self):
        response = self.client.get(f"/api/instance_settings/RECORDINGS_TTL_WEEKS")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], 3)

        response = self.client.patch(f"/api/instance_settings/RECORDINGS_TTL_WEEKS", {"value": 5})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["value"], 5)

        self.assertEqual(get_instance_setting("RECORDINGS_TTL_WEEKS"), 5)

        table_engine = sync_execute(
            "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(table)s",
            {"database": CLICKHOUSE_DATABASE, "table": SESSION_RECORDING_EVENTS_DATA_TABLE()},
        )
        self.assertIn("TTL toDate(created_at) + toIntervalWeek(5)", table_engine[0][0])
