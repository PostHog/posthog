import base64
import json
from datetime import timedelta
from unittest.mock import ANY, call, patch
from urllib.parse import quote

from django.core.cache import cache
from django.utils.timezone import now
from freezegun.api import freeze_time
from rest_framework import status

from posthog import models, rate_limit
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.models.instance_setting import override_instance_config
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

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_default_burst_rate_limit(self, rate_limit_enabled_mock, incr_mock):
        for _ in range(5):
            response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # mock_calls call object is a tuple of (function, args, kwargs)
        # so the incremented metric is args[0]
        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 1)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "burst",
                "rate": "5/minute",
                "path": "/api/projects/TEAM_ID/feature_flags",
            },
        )

    @patch("posthog.rate_limit.SustainedRateThrottle.rate", new="5/hour")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_default_sustained_rate_limit(self, rate_limit_enabled_mock, incr_mock):
        base_time = now()
        for _ in range(5):
            with freeze_time(base_time):
                response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
                base_time += timedelta(seconds=61)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with freeze_time(base_time):
            for _ in range(2):
                response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(
                len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 2
            )
            incr_mock.assert_any_call(
                "rate_limit_exceeded",
                tags={
                    "team_id": self.team.pk,
                    "scope": "sustained",
                    "rate": "5/hour",
                    "path": "/api/projects/TEAM_ID/feature_flags",
                },
            )

    @patch("posthog.rate_limit.ClickHouseBurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_clickhouse_burst_rate_limit(self, rate_limit_enabled_mock, incr_mock):
        # Does nothing on /feature_flags endpoint
        for _ in range(10):
            response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls

        for _ in range(5):
            response = self.client.get(f"/api/projects/{self.team.pk}/events")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/projects/{self.team.pk}/events")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 1)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "clickhouse_burst",
                "rate": "5/minute",
                "path": "/api/projects/TEAM_ID/events",
            },
        )

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_rate_limits_are_based_on_the_team_not_user(self, rate_limit_enabled_mock, incr_mock):
        for _ in range(5):
            response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # First user gets rate limited
        response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 1)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "burst",
                "rate": "5/minute",
                "path": f"/api/projects/TEAM_ID/feature_flags",
            },
        )

        # Create a new user
        new_user = create_user(email="test@posthog.com", password="1234", organization=self.organization)
        self.client.force_login(new_user)

        incr_mock.reset_mock()

        # Second user gets rate limited after a single request
        response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 1)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "burst",
                "rate": "5/minute",
                "path": f"/api/projects/TEAM_ID/feature_flags",
            },
        )

        # Create a new team
        new_team = create_team(organization=self.organization)

        incr_mock.reset_mock()

        # Requests to the new team are not rate limited
        response = self.client.get(f"/api/projects/{new_team.pk}/feature_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 0)

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_rate_limits_work_on_non_team_endpoints(self, rate_limit_enabled_mock, incr_mock):
        for _ in range(5):
            response = self.client.get(f"/api/organizations/{self.organization.pk}/plugins")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/organizations/{self.organization.pk}/plugins")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 1)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": None,
                "scope": "burst",
                "rate": "5/minute",
                "path": f"/api/organizations/ORG_ID/plugins",
            },
        )

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_rate_limits_unauthenticated_users(self, rate_limit_enabled_mock, incr_mock):
        self.client.logout()
        for _ in range(5):
            # Hitting the login endpoint because it allows for unauthenticated requests
            response = self.client.post(f"/api/login")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(f"/api/login")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        self.assertEqual(len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]), 1)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": None,
                "scope": "burst",
                "rate": "5/minute",
                "path": "/api/login",
            },
        )

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_does_not_rate_limit_capture_endpoints(self, kafka_mock, rate_limit_enabled_mock, incr_mock):
        data = {"event": "$autocapture", "properties": {"distinct_id": 2, "token": self.team.api_token}}
        for _ in range(6):
            response = self.client.get("/e/?data=%s" % quote(json.dumps(data)), HTTP_ORIGIN="https://localhost")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_does_not_rate_limit_decide_endpoints(self, rate_limit_enabled_mock, incr_mock):
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
        assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=False)
    def test_does_not_rate_limit_if_rate_limit_disabled(self, rate_limit_enabled_mock, incr_mock):
        for _ in range(6):
            response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_does_not_call_get_instance_setting_for_every_request(self, rate_limit_enabled_mock, incr_mock):
        with freeze_time("2022-04-01 12:34:45") as frozen_time:
            with override_instance_config("RATE_LIMITING_ALLOW_LIST_TEAMS", f"{self.team.pk}"):
                with patch.object(
                    rate_limit, "get_instance_setting", wraps=models.instance_setting.get_instance_setting
                ) as wrapped_get_instance_setting:
                    for _ in range(10):
                        self.client.get(f"/api/projects/{self.team.pk}/feature_flags")

                    assert wrapped_get_instance_setting.call_count == 1

                    frozen_time.tick(delta=timedelta(seconds=65))
                    for _ in range(10):
                        self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
                    assert wrapped_get_instance_setting.call_count == 2

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_allow_list_works_as_expected(self, rate_limit_enabled_mock, incr_mock):
        with freeze_time("2022-04-01 12:34:45"):
            with override_instance_config("RATE_LIMITING_ALLOW_LIST_TEAMS", f"{self.team.pk}"):
                for _ in range(10):
                    response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags")
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls
