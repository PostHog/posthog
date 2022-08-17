import base64
import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import quote

from django.core.cache import cache
from django.utils.timezone import now
from freezegun.api import freeze_time
from rest_framework import status

from posthog.test.base import APIBaseTest


class TestUserAPI(APIBaseTest):
    def setUp(self):
        # ensure the rate limit is reset for each test
        cache.clear()
        return super().setUp()

    def tearDown(self):
        # ensure the rate limit is reset for any subsequent non-rate-limit tests
        cache.clear()
        return super().tearDown()

    @patch("posthog.rate_limit.PassThroughBurstRateThrottle.get_rate", return_value="5/minute")
    @patch("posthog.rate_limit.incr")
    def test_burst_rate_limit(self, incr_mock, _):
        for _ in range(5):
            response = self.client.get(f"/api/projects/{self.team.pk}/insights")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Does not actually block the request, but increments the counter
        response = self.client.get(f"/api/projects/{self.team.pk}/insights")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(incr_mock.call_count, 1)
        incr_mock.assert_called_with(
            "rate_limit_exceeded", tags={"team_id": self.team.pk, "scope": "burst"},
        )

    @patch("posthog.rate_limit.PassThroughSustainedRateThrottle.get_rate", return_value="5/hour")
    @patch("posthog.rate_limit.incr")
    def test_sustained_rate_limit(self, incr_mock, _):
        base_time = now()
        for _ in range(5):
            with freeze_time(base_time):
                response = self.client.get(f"/api/projects/{self.team.pk}/insights")
                base_time += timedelta(seconds=61)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with freeze_time(base_time):
            # Does not actually block the request, but increments the counter
            response = self.client.get(f"/api/projects/{self.team.pk}/insights")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(incr_mock.call_count, 1)
            incr_mock.assert_called_with(
                "rate_limit_exceeded", tags={"team_id": self.team.pk, "scope": "sustained",},
            )

    @patch("posthog.rate_limit.PassThroughBurstRateThrottle.get_rate", return_value="5/minute")
    @patch("posthog.rate_limit.incr")
    def test_rate_limits_unauthenticated_users(self, incr_mock, _):
        self.client.logout()
        for _ in range(5):
            # Hitting the login endpoint because it allows for unauthenticated requests
            response = self.client.post(f"/api/login")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Does not actually block the request, but increments the counter
        response = self.client.post(f"/api/login")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(incr_mock.call_count, 1)
        incr_mock.assert_called_with(
            "rate_limit_exceeded", tags={"team_id": None, "scope": "burst",},
        )

    @patch("posthog.rate_limit.PassThroughBurstRateThrottle.get_rate", return_value="5/minute")
    @patch("posthog.rate_limit.incr")
    def test_does_not_rate_limit_capture_endpoints(self, incr_mock, _):
        data = {
            "event": "$autocapture",
            "properties": {"distinct_id": 2, "token": self.team.api_token,},
        }
        for _ in range(6):
            response = self.client.get("/e/?data=%s" % quote(json.dumps(data)), HTTP_ORIGIN="https://localhost",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(incr_mock.call_count, 0)

    @patch("posthog.rate_limit.PassThroughBurstRateThrottle.get_rate", return_value="5/minute")
    @patch("posthog.rate_limit.incr")
    def test_does_not_rate_limit_decide_endpoints(self, incr_mock, _):
        for _ in range(6):
            response = self.client.post(
                f"/decide/?v=2",
                {
                    "data": base64.b64encode(
                        json.dumps({"token": self.team.api_token, "distinct_id": "2"}).encode("utf-8")
                    ).decode("utf-8")
                },
                HTTP_ORIGIN="https://localhost",
                REMOTE_ADDR="0.0.0.0",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(incr_mock.call_count, 0)
