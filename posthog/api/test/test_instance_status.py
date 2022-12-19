from unittest.mock import patch

import pytest
from rest_framework import status

from posthog.test.base import APIBaseTest


class TestInstanceStatus(APIBaseTest):
    @pytest.mark.skip_on_multitenancy
    def test_instance_status_routes(self):
        self.assertEqual(self.client.get("/api/instance_status").status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get("/api/instance_status/navigation").status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get("/api/instance_status/queries").status_code, status.HTTP_200_OK)

    def test_object_storage_when_disabled(self):
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            response = self.client.get("/api/instance_status")
        json = response.json()

        object_storage_metrics = [o for o in json["results"]["overview"] if o.get("key", None) == "object_storage"]
        self.assertEqual(
            object_storage_metrics, [{"key": "object_storage", "metric": "Object Storage enabled", "value": False}]
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
                    {"key": "object_storage", "metric": "Object Storage enabled", "value": True},
                    {"key": "object_storage", "metric": "Object Storage healthy", "value": False},
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
                    {"key": "object_storage", "metric": "Object Storage enabled", "value": True},
                    {"key": "object_storage", "metric": "Object Storage healthy", "value": True},
                ],
            )

    def test_navigation_ok(self):
        response = self.client.get("/api/instance_status/navigation").json()
        self.assertEqual(
            response,
            {
                "system_status_ok": True,
                "async_migrations_ok": True,
            },
        )

    @patch("posthog.api.instance_status.is_postgres_alive")
    @patch("posthog.api.instance_status.async_migrations_ok")
    def test_navigation_not_ok(self, mock_is_postgres_alive, mock_async_migrations_ok):
        mock_is_postgres_alive.return_value = False
        mock_async_migrations_ok.return_value = False

        response = self.client.get("/api/instance_status/navigation").json()

        self.assertEqual(
            response,
            {
                "system_status_ok": False,
                "async_migrations_ok": False,
            },
        )
