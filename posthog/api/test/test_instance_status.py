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
