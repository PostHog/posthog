import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status


class TestInstanceStatus(APIBaseTest):
    @pytest.mark.skip_on_multitenancy
    def test_instance_status_routes(self):
        self.assertEqual(self.client.get("/api/instance_status").status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.get("/api/instance_status/navigation").status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.get("/api/instance_status/queries").status_code,
            status.HTTP_200_OK,
        )

    def test_object_storage_when_disabled(self):
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            response = self.client.get("/api/instance_status")
        json = response.json()

        object_storage_metrics = [o for o in json["results"]["overview"] if o.get("key", None) == "object_storage"]
        self.assertEqual(
            object_storage_metrics,
            [
                {
                    "key": "object_storage",
                    "metric": "Object Storage enabled",
                    "value": False,
                }
            ],
        )

    @patch("posthog.storage.object_storage._client")
    def test_object_storage_when_enabled_but_unhealthy(self, patched_s3_client):
        patched_s3_client.head_bucket.return_value = False

        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self.client.get("/api/instance_status")
            json = response.json()

            object_storage_metrics = [o for o in json["results"]["overview"] if o.get("key", None) == "object_storage"]
            self.assertEqual(
                object_storage_metrics,
                [
                    {
                        "key": "object_storage",
                        "metric": "Object Storage enabled",
                        "value": True,
                    },
                    {
                        "key": "object_storage",
                        "metric": "Object Storage healthy",
                        "value": False,
                    },
                ],
            )

    @patch("posthog.storage.object_storage._client")
    def test_object_storage_when_enabled_and_healthy(self, patched_s3_client):
        patched_s3_client.head_bucket.return_value = True

        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self.client.get("/api/instance_status")
            json = response.json()

            object_storage_metrics = [o for o in json["results"]["overview"] if o.get("key", None) == "object_storage"]
            self.assertEqual(
                object_storage_metrics,
                [
                    {
                        "key": "object_storage",
                        "metric": "Object Storage enabled",
                        "value": True,
                    },
                    {
                        "key": "object_storage",
                        "metric": "Object Storage healthy",
                        "value": True,
                    },
                ],
            )

    @patch("posthog.api.instance_status.is_postgres_alive")
    @patch("posthog.api.instance_status.is_redis_alive")
    @patch("posthog.api.instance_status.is_plugin_server_alive")
    # patched at the module level because it is locally imported in the target code
    @patch("posthog.clickhouse.system_status.dead_letter_queue_ratio_ok_cached")
    @patch("posthog.api.instance_status.async_migrations_ok")
    def test_navigation_ok(self, *mocks):
        for mock in mocks:
            mock.return_value = True

        response = self.client.get("/api/instance_status/navigation").json()
        self.assertEqual(
            response,
            {
                "system_status_ok": True,
                "async_migrations_ok": True,
            },
        )

    @patch("posthog.api.instance_status.is_postgres_alive")
    @patch("posthog.api.instance_status.is_redis_alive")
    @patch("posthog.api.instance_status.is_plugin_server_alive")
    # patched at the module level because it is locally imported in the target code
    @patch("posthog.clickhouse.system_status.dead_letter_queue_ratio_ok_cached")
    @patch("posthog.api.instance_status.async_migrations_ok")
    def test_navigation_not_ok(self, *mocks):
        for mock in mocks:
            mock.return_value = False

        response = self.client.get("/api/instance_status/navigation").json()

        self.assertEqual(
            response,
            {
                "system_status_ok": False,
                "async_migrations_ok": False,
            },
        )

    @patch("posthog.api.instance_status.is_postgres_alive")
    @patch("posthog.api.instance_status.is_redis_alive")
    @patch("posthog.api.instance_status.is_plugin_server_alive")
    # patched at the module level because it is locally imported in the target code
    @patch("posthog.clickhouse.system_status.dead_letter_queue_ratio_ok_cached")
    def test_navigation_on_cloud(self, *mocks):
        self.user.is_staff = True
        self.user.save()

        with self.is_cloud(True):
            response = self.client.get("/api/instance_status/navigation").json()

        self.assertEqual(
            response,
            {
                "system_status_ok": True,
                "async_migrations_ok": True,
            },
        )

        for mock in mocks:
            self.assertEqual(mock.call_count, 0)
