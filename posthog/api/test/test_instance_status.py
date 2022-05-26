from unittest.mock import patch

import pytest
from rest_framework import status

from posthog.test.base import APIBaseTest


class TestInstanceStatus(APIBaseTest):
    @pytest.mark.skip_on_multitenancy
    def test_instance_status_routes(self):
        self.assertEqual(self.client.get("/api/instance_status").status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get("/api/instance_status/queries").status_code, status.HTTP_200_OK)

    @patch("posthog.internal_metrics.timing")
    @patch("posthog.internal_metrics.incr")
    def test_create_internal_metrics_route(self, incr_mock, timing_mock):
        self.client.post("/api/instance_status/capture", {"method": "incr", "metric": "foo", "value": 1})
        incr_mock.assert_called_with("foo", 1, None)

        self.client.post(
            "/api/instance_status/capture", {"method": "timing", "metric": "bar", "value": 15.2, "tags": {"team_id": 1}}
        )
        timing_mock.assert_called_with("bar", 15.2, {"team_id": 1})

    def test_object_storage_when_disabled(self):
        with self.settings(OBJECT_STORAGE_ENABLED=False,):
            response = self.client.get("/api/instance_status")
        json = response.json()

        object_storage_metrics = [o for o in json["results"]["overview"] if o.get("key", None) == "object_storage"]
        self.assertEqual(
            object_storage_metrics, [{"key": "object_storage", "metric": "Object Storage enabled", "value": False}]
        )

    @patch("posthog.storage.object_storage.object_storage_client")
    def test_object_storage_when_enabled_but_unhealthy(self, patched_s3_client):
        patched_s3_client.return_value.head_bucket.return_value = False

        with self.settings(OBJECT_STORAGE_ENABLED=True,):
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

    @patch("posthog.storage.object_storage.object_storage_client")
    def test_object_storage_when_enabled_and_healthy(self, patched_s3_client):
        patched_s3_client.return_value.head_bucket.return_value = True

        with self.settings(OBJECT_STORAGE_ENABLED=True,):
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
