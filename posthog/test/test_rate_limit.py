import json
import base64
from datetime import timedelta
from urllib.parse import quote

from freezegun.api import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import ANY, Mock, call, patch

from django.core.cache import cache
from django.test.client import Client
from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status

from posthog import models, rate_limit
from posthog.api.feature_flag import LocalEvaluationThrottle, RemoteConfigThrottle
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.models import Team
from posthog.models.instance_setting import override_instance_config
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle, HogQLQueryThrottle, get_route_from_path


class TestUserAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

        # ensure the rate limit is reset for each test
        cache.clear()

        self.personal_api_key = generate_random_token_personal()
        self.hashed_personal_api_key = hash_key_value(self.personal_api_key)
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            secure_value=hash_key_value(self.personal_api_key),
        )

    def tearDown(self):
        super().tearDown()

        # ensure the rate limit is reset for any subsequent non-rate-limit tests
        cache.clear()

    def test_load_team_rate_limit_from_cache(self):
        throttle = HogQLQueryThrottle()

        # Set up cache with test data
        cache_key = f"team_ratelimit_query_{self.team.id}"
        cache.set(cache_key, "100/hour")

        # Test loading from cache
        throttle.load_team_rate_limit(self.team.pk)

        self.assertEqual(throttle.rate, "100/hour")
        self.assertEqual(throttle.num_requests, 100)
        self.assertEqual(throttle.duration, 3600)  # 1 hour in seconds

    def test_load_team_rate_limit_from_db(self):
        throttle = HogQLQueryThrottle()

        # Clear cache to ensure DB lookup
        cache_key = f"team_ratelimit_query_{self.team.id}"
        cache.delete(cache_key)

        # Set custom rate limit on team
        self.team.api_query_rate_limit = "200/day"
        self.team.save()

        # Test loading from DB
        throttle.load_team_rate_limit(self.team.id)

        self.assertEqual(throttle.rate, "200/day")
        self.assertEqual(throttle.num_requests, 200)
        self.assertEqual(throttle.duration, 86400)  # 24 hours in seconds

        # Verify it was cached
        cache_key = f"team_ratelimit_query_{self.team.pk}"
        self.assertEqual(cache.get(cache_key), "200/day")

    def test_load_team_rate_limit_no_custom_limit(self):
        throttle = HogQLQueryThrottle()

        # Clear cache to ensure DB lookup
        cache_key = f"team_ratelimit_query_{self.team.id}"
        cache.delete(cache_key)

        # no custom rate limit
        self.team.api_query_rate_limit = None
        self.team.save()

        # Test loading with no custom limit
        throttle.load_team_rate_limit(self.team.pk)

        # Should not set rate when no custom limit exists
        self.assertEqual(throttle.rate, HogQLQueryThrottle.rate)

        # Verify nothing was cached
        self.assertIsNone(cache.get(cache_key))

    @patch("posthog.models.Team.objects.get")
    def test_load_team_rate_limit_team_does_not_exist(self, mock_team_get):
        throttle = HogQLQueryThrottle()

        # Simulate team not found
        mock_team_get.side_effect = Team.DoesNotExist

        # Test loading with non-existent team
        with self.assertRaises(Team.DoesNotExist):
            throttle.load_team_rate_limit(999999)

        # Verify nothing was cached
        cache_key = f"team_ratelimit_test_999999"
        self.assertIsNone(cache.get(cache_key))

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_default_burst_rate_limit(self, rate_limit_enabled_mock, incr_mock):
        for _ in range(5):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags",
                HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags",
            HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # mock_calls call object is a tuple of (function, args, kwargs)
        # so the incremented metric is args[0]
        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            1,
        )
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "burst",
                "rate": "5/minute",
                "route": "/api/projects/TEAM_ID/feature_flags/",
                "hashed_personal_api_key": self.hashed_personal_api_key,
            },
        )

    @patch("posthog.rate_limit.SustainedRateThrottle.rate", new="5/hour")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_default_sustained_rate_limit(self, rate_limit_enabled_mock, incr_mock):
        base_time = now()
        for _ in range(5):
            with freeze_time(base_time):
                response = self.client.get(
                    f"/api/projects/{self.team.pk}/feature_flags",
                    HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
                )
                base_time += timedelta(seconds=61)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with freeze_time(base_time):
            for _ in range(2):
                response = self.client.get(
                    f"/api/projects/{self.team.pk}/feature_flags",
                    HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
                )
                self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(
                len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
                2,
            )
            incr_mock.assert_any_call(
                "rate_limit_exceeded",
                tags={
                    "team_id": self.team.pk,
                    "scope": "sustained",
                    "rate": "5/hour",
                    "route": "/api/projects/TEAM_ID/feature_flags/",
                    "hashed_personal_api_key": self.hashed_personal_api_key,
                },
            )

    @patch("posthog.rate_limit.ClickHouseBurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_clickhouse_burst_rate_limit(self, rate_limit_enabled_mock, incr_mock):
        # Does nothing on /feature_flags endpoint
        for _ in range(10):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags",
                HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls

        for _ in range(5):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/events",
                HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Does not actually block the request, but increments the counter
        response = self.client.get(
            f"/api/projects/{self.team.pk}/events",
            HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            1,
        )
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "clickhouse_burst",
                "rate": "5/minute",
                "route": "/api/projects/TEAM_ID/events/",
                "hashed_personal_api_key": self.hashed_personal_api_key,
            },
        )

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_rate_limits_are_based_on_api_key_not_user(self, rate_limit_enabled_mock, incr_mock):
        self.client.logout()
        for _ in range(5):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/feature_flags",
                HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # First user gets rate limited
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags",
            HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            1,
        )
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "burst",
                "rate": "5/minute",
                "route": "/api/projects/TEAM_ID/feature_flags/",
                "hashed_personal_api_key": self.hashed_personal_api_key,
            },
        )

        # Create a new user
        new_user = create_user(email="test@posthog.com", password="1234", organization=self.organization)
        new_personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=new_user, secure_value=hash_key_value(new_personal_api_key))
        self.client.force_login(new_user)

        incr_mock.reset_mock()

        # Second user gets rate limited after a single request
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags",
            HTTP_AUTHORIZATION=f"Bearer {new_personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Create a new team
        new_team = create_team(organization=self.organization)
        new_user = create_user(email="test2@posthog.com", password="1234", organization=self.organization)
        new_personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=new_user, secure_value=hash_key_value(new_personal_api_key))

        incr_mock.reset_mock()

        # Requests to the new team are not rate limited
        response = self.client.get(
            f"/api/projects/{new_team.pk}/feature_flags",
            HTTP_AUTHORIZATION=f"Bearer {new_personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            0,
        )

        # until it hits their specific limit
        for _ in range(5):
            response = self.client.get(
                f"/api/projects/{new_team.pk}/feature_flags",
                HTTP_AUTHORIZATION=f"Bearer {new_personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            1,
        )

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_rate_limits_work_on_non_team_endpoints(self, rate_limit_enabled_mock, incr_mock):
        self.client.logout()
        for _ in range(5):
            response = self.client.get(
                f"/api/organizations/{self.organization.pk}/plugins",
                HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(
            f"/api/organizations/{self.organization.pk}/plugins",
            HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            1,
        )
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": None,
                "scope": "burst",
                "rate": "5/minute",
                "route": "/api/organizations/ORG_ID/plugins/",
                "hashed_personal_api_key": self.hashed_personal_api_key,
            },
        )

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_does_not_rate_limit_non_personal_api_key_endpoints(self, rate_limit_enabled_mock, incr_mock):
        self.client.logout()

        for _ in range(6):
            response = self.client.get(
                f"/api/organizations/{self.organization.pk}/plugins",
                HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
            )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        # got rate limited with personal API key
        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            1,
        )
        incr_mock.reset_mock()

        # if not logged in, we 401
        for _ in range(3):
            response = self.client.get(f"/api/organizations/{self.organization.pk}/plugins")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_login(self.user)
        # but no rate limits when logged in and not using personal API key
        response = self.client.get(f"/api/organizations/{self.organization.pk}/plugins")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            0,
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
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS, response.content)

        self.assertEqual(
            len([1 for name, args, kwargs in incr_mock.mock_calls if args[0] == "rate_limit_exceeded"]),
            1,
        )
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": None,
                "scope": "burst",
                "rate": "5/minute",
                "route": "/api/login/",
                "hashed_personal_api_key": None,
            },
        )

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("posthog.kafka_client.client._KafkaProducer.produce")
    def test_does_not_rate_limit_capture_endpoints(self, kafka_mock, rate_limit_enabled_mock, incr_mock):
        data = {
            "event": "$autocapture",
            "properties": {"distinct_id": 2, "token": self.team.api_token},
        }
        for _ in range(6):
            response = self.client.get("/e/?data={}".format(quote(json.dumps(data))), HTTP_ORIGIN="https://localhost")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_does_not_rate_limit_decide_endpoints(self, rate_limit_enabled_mock, incr_mock):
        decide_client = Client(enforce_csrf_checks=True)
        for _ in range(6):
            response = decide_client.post(
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
                    rate_limit,
                    "get_instance_setting",
                    wraps=models.instance_setting.get_instance_setting,
                ) as wrapped_get_instance_setting:
                    for _ in range(10):
                        self.client.get(
                            f"/api/projects/{self.team.pk}/feature_flags",
                            HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
                        )

                    assert wrapped_get_instance_setting.call_count == 1

                    frozen_time.tick(delta=timedelta(seconds=65))
                    for _ in range(10):
                        self.client.get(
                            f"/api/projects/{self.team.pk}/feature_flags",
                            HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
                        )
                    assert wrapped_get_instance_setting.call_count == 2

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_allow_list_works_as_expected(self, rate_limit_enabled_mock, incr_mock):
        with freeze_time("2022-04-01 12:34:45"):
            with override_instance_config("RATE_LIMITING_ALLOW_LIST_TEAMS", f"{self.team.pk}"):
                for _ in range(10):
                    response = self.client.get(
                        f"/api/projects/{self.team.pk}/feature_flags",
                        HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key}",
                    )
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls

    @patch("posthog.rate_limit.report_user_action")
    def test_ai_burst_rate_throttle_calls_report_user_action(self, mock_report_user_action):
        """Test that AIBurstRateThrottle calls report_user_action when rate limit is exceeded"""
        throttle = AIBurstRateThrottle()

        mock_request = Mock()
        mock_request.user = self.user
        mock_view = Mock()

        # Mock the parent allow_request to return False (rate limited)
        with patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=False):
            result = throttle.allow_request(mock_request, mock_view)

            # Should return False (rate limited)
            self.assertFalse(result)

            # Should call report_user_action with correct parameters
            mock_report_user_action.assert_called_once_with(self.user, "ai burst rate limited")

    @patch("posthog.rate_limit.report_user_action")
    def test_ai_sustained_rate_throttle_calls_report_user_action(self, mock_report_user_action):
        """Test that AISustainedRateThrottle calls report_user_action when rate limit is exceeded"""
        throttle = AISustainedRateThrottle()

        mock_request = Mock()
        mock_request.user = self.user
        mock_view = Mock()

        # Mock the parent allow_request to return False (rate limited)
        with patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=False):
            result = throttle.allow_request(mock_request, mock_view)

            # Should return False (rate limited)
            self.assertFalse(result)

            # Should call report_user_action with correct parameters
            mock_report_user_action.assert_called_once_with(self.user, "ai sustained rate limited")

    def test_local_evaluation_throttle_uses_default_rate_when_no_custom_limit(self):
        throttle = LocalEvaluationThrottle()

        # Mock view and request
        mock_view = Mock()
        mock_request = Mock()

        with (
            patch("posthog.api.feature_flag.LOCAL_EVAL_RATE_LIMITS", {}),
            patch.object(throttle, "safely_get_team_id_from_view", return_value=123),
            patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True),
        ):
            result = throttle.allow_request(mock_request, mock_view)

            self.assertTrue(result)
            # Rate should remain default
            self.assertEqual(throttle.rate, "600/minute")

    def test_local_evaluation_throttle_handles_empty_settings(self):
        throttle = LocalEvaluationThrottle()

        # Mock view and request
        mock_view = Mock()
        mock_request = Mock()

        with (
            patch("posthog.api.feature_flag.LOCAL_EVAL_RATE_LIMITS", {}),
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch.object(throttle, "safely_get_team_id_from_view", return_value=123),
            patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True),
        ):
            result = throttle.allow_request(mock_request, mock_view)

            self.assertTrue(result)
            # Should use default rate
            self.assertEqual(throttle.rate, "600/minute")

    def test_local_evaluation_throttle_handles_missing_team_gracefully(self):
        throttle = LocalEvaluationThrottle()

        # Mock view without team_id
        mock_view = Mock()
        mock_view.team_id = None

        # Test with missing team
        with patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True):
            with patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True):
                result = throttle.allow_request(Mock(), mock_view)

                self.assertTrue(result)
                # Should keep default rate
                self.assertEqual(throttle.rate, "600/minute")

    def test_local_evaluation_throttle_uses_custom_rate_for_team(self):
        throttle = LocalEvaluationThrottle()

        # Mock view and request
        mock_view = Mock()
        mock_request = Mock()

        with (
            patch("posthog.api.feature_flag.LOCAL_EVAL_RATE_LIMITS", {123: "1200/minute"}),
            patch.object(throttle, "safely_get_team_id_from_view", return_value=123),
            patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True),
        ):
            result = throttle.allow_request(mock_request, mock_view)

            self.assertTrue(result)
            # Should use custom rate
            self.assertEqual(throttle.rate, "1200/minute")
            self.assertEqual(throttle.num_requests, 1200)
            self.assertEqual(throttle.duration, 60)  # 1 minute in seconds

    def test_remote_config_throttle_uses_default_rate_when_no_custom_limit(self):
        throttle = RemoteConfigThrottle()

        # Mock view and request
        mock_view = Mock()
        mock_request = Mock()

        with (
            patch("posthog.api.feature_flag.REMOTE_CONFIG_RATE_LIMITS", {}),
            patch.object(throttle, "safely_get_team_id_from_view", return_value=123),
            patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True),
        ):
            result = throttle.allow_request(mock_request, mock_view)

            self.assertTrue(result)
            # Rate should remain default
            self.assertEqual(throttle.rate, "600/minute")

    def test_remote_config_throttle_handles_empty_settings(self):
        throttle = RemoteConfigThrottle()

        # Mock view and request
        mock_view = Mock()
        mock_request = Mock()

        with (
            patch("posthog.api.feature_flag.REMOTE_CONFIG_RATE_LIMITS", {}),
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch.object(throttle, "safely_get_team_id_from_view", return_value=123),
            patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True),
        ):
            result = throttle.allow_request(mock_request, mock_view)

            self.assertTrue(result)
            # Should use default rate
            self.assertEqual(throttle.rate, "600/minute")

    def test_remote_config_throttle_handles_missing_team_gracefully(self):
        throttle = RemoteConfigThrottle()

        # Mock view without team_id
        mock_view = Mock()
        mock_view.team_id = None

        # Test with missing team
        with patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True):
            with patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True):
                result = throttle.allow_request(Mock(), mock_view)

                self.assertTrue(result)
                # Should keep default rate
                self.assertEqual(throttle.rate, "600/minute")

    def test_remote_config_throttle_uses_custom_rate_for_team(self):
        throttle = RemoteConfigThrottle()

        # Mock view and request
        mock_view = Mock()
        mock_request = Mock()

        with (
            patch("posthog.api.feature_flag.REMOTE_CONFIG_RATE_LIMITS", {123: "1200/minute"}),
            patch.object(throttle, "safely_get_team_id_from_view", return_value=123),
            patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True),
        ):
            result = throttle.allow_request(mock_request, mock_view)

            self.assertTrue(result)
            # Should use custom rate
            self.assertEqual(throttle.rate, "1200/minute")
            self.assertEqual(throttle.num_requests, 1200)
            self.assertEqual(throttle.duration, 60)  # 1 minute in seconds

    @parameterized.expand(
        [
            # Test Django route pattern normalization
            (
                "/api/environments/123/query/abc-123-def/progress/",
                "api/environments/<int:team_id>/query/<str:query_uuid>/progress/",
                "/api/environments/TEAM_ID/query/QUERY_UUID/progress/",
                "Django route pattern with int and str parameters",
            ),
            (
                "/api/projects/123/feature_flags/",
                "^api/projects/(?P<parent_lookup_project_id>[^/.]+)/feature_flags/?$",
                "/api/projects/TEAM_ID/feature_flags/",
                "Django route pattern with named regexp parameters",
            ),
            (
                "/api/projects/123/recordings/session-recordings-id-1234",
                "/api/projects/<team_id>/recordings/(?P<session_recording_id>[^/.]+)",
                "/api/projects/TEAM_ID/recordings/SESSION_RECORDING_ID/",
                "session recordings",
            ),
            # # Test fallback pattern for projects
            (
                "/api/projects/123/some/endpoint",
                None,  # resolve will raise exception
                "/api/projects/TEAM_ID/some/endpoint",
                "Fallback pattern for team/project IDs",
            ),
            # Test fallback pattern for organizations
            (
                "/api/organizations/org-123/plugins",
                None,  # resolve will raise exception
                "/api/organizations/ORG_ID/plugins",
                "Fallback pattern for organization IDs",
            ),
            # Test empty/None paths
            ("", None, "", "Empty path"),
            (None, None, "", "None path"),
            # Test when resolve returns no route
            (
                "/some/path",
                None,  # resolve returns object with route=None
                "/some/path",
                "No route pattern found",
            ),
        ]
    )
    @patch("posthog.rate_limit.statsd.incr")
    def test_get_route_from_path(self, test_path, mock_route, expected_result, description, incr_mock):
        """Test that get_route_from_path correctly extracts and normalizes route patterns"""
        if test_path in ("", None):
            # Direct test for empty/None paths
            result = get_route_from_path(test_path)
            self.assertEqual(result, expected_result, description)
        else:
            # Test Django route pattern normalization
            with patch("posthog.rate_limit.patchable_resolve") as mock_resolve:
                mock_resolved = Mock()
                mock_resolved.route = mock_route
                mock_resolve.return_value = mock_resolved
                if mock_route is None and test_path == "/some/path":
                    mock_resolve.side_effect = Exception("Route not found")

                result = get_route_from_path(test_path)
                self.assertEqual(expected_result, result, description)
