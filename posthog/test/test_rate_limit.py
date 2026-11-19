import json
import time
import socket
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext, suppress
from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import ANY, Mock, call, patch

from django.conf import settings
from django.core.cache import cache, caches
from django.test import SimpleTestCase, override_settings
from django.utils.timezone import now

from django_redis.cache import RedisCache
from parameterized import parameterized
from prometheus_client import REGISTRY
from redis import Redis
from rest_framework import exceptions, status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from posthog import models, rate_limit
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.caching.throttle_history_cache import throttle_history_cache
from posthog.exceptions import exception_handler
from posthog.models import Team
from posthog.models.instance_setting import override_instance_config
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_personal, generate_random_token_secret, hash_key_value
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AIResearchBurstRateThrottle,
    AIResearchSustainedRateThrottle,
    AISustainedRateThrottle,
    HogQLQueryThrottle,
    LLMPromptPublishBurstRateThrottle,
    get_route_from_path,
)
from posthog.test.lagging_redis_reader import lagging_reader_caches, unique_key_prefix

from products.feature_flags.backend.api.feature_flag import (
    RemoteConfigProjectSecretApiKeyTeamThrottle,
    RemoteConfigThrottle,
)
from products.messaging.backend.presentation.views.message_templates import (
    TransactionalEmailBurstThrottle,
    TransactionalEmailSustainedThrottle,
    TransactionalEmailTeamBurstThrottle,
    TransactionalEmailTeamSustainedThrottle,
)


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
            scopes=["*"],
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
                headers={"authorization": f"Bearer {self.personal_api_key}"},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags", headers={"authorization": f"Bearer {self.personal_api_key}"}
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

    @parameterized.expand(
        [
            ("body",),
            ("query_string",),
        ]
    )
    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_burst_rate_limit_applies_to_every_personal_api_key_source(self, source, rate_limit_enabled_mock):
        # The client is logged in by default, and a session would authenticate the request on its own,
        # hiding whether the personal API key was picked up at all.
        self.client.logout()

        url = f"/api/projects/{self.team.pk}/feature_flags/"
        body: dict = {}
        if source == "body":
            body["personal_api_key"] = self.personal_api_key
        else:
            url = f"{url}?personal_api_key={quote(self.personal_api_key)}"

        for _ in range(5):
            response = self.client.post(url, body, format="json")
            # The body omits the required fields, so the endpoint rejects it. What matters is that
            # the request reached the endpoint, which means it authenticated and was not throttled.
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

        response = self.client.post(url, body, format="json")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS, response.content)

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_burst_rate_limit_shares_one_bucket_across_key_sources(self, rate_limit_enabled_mock):
        # One key gets one budget. If each source got its own bucket, alternating between them
        # would multiply what a single key is allowed.
        self.client.logout()

        url = f"/api/projects/{self.team.pk}/feature_flags/"
        requests = [
            lambda: self.client.post(url, {"personal_api_key": self.personal_api_key}, format="json"),
            lambda: self.client.post(url, {}, headers={"authorization": f"Bearer {self.personal_api_key}"}),
        ]

        for index in range(5):
            response = requests[index % 2]()
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

        response = requests[1]()
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS, response.content)

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_burst_rate_limit_ignores_an_unvalidated_query_string_key(self, rate_limit_enabled_mock):
        # Authentication reads the header, then the body, then the query string, and stops at the
        # first hit. A request that authenticates on its body key never validates the query string,
        # so bucketing on that value would let a caller mint a fresh budget on every request.
        self.client.logout()

        for index in range(5):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/feature_flags/?personal_api_key=junk-{index}",
                {"personal_api_key": self.personal_api_key},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/?personal_api_key=junk-5",
            {"personal_api_key": self.personal_api_key},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS, response.content)

    @patch("posthog.rate_limit.SustainedRateThrottle.rate", new="5/hour")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_default_sustained_rate_limit(self, rate_limit_enabled_mock, incr_mock):
        base_time = now()
        for _ in range(5):
            with time_machine.travel(base_time, tick=False):
                response = self.client.get(
                    f"/api/projects/{self.team.pk}/feature_flags",
                    headers={"authorization": f"Bearer {self.personal_api_key}"},
                )
                base_time += timedelta(seconds=61)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with time_machine.travel(base_time, tick=False):
            for _ in range(2):
                response = self.client.get(
                    f"/api/projects/{self.team.pk}/feature_flags",
                    headers={"authorization": f"Bearer {self.personal_api_key}"},
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
                headers={"authorization": f"Bearer {self.personal_api_key}"},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert call("rate_limit_exceeded", tags=ANY) not in incr_mock.mock_calls

        for _ in range(5):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/events", headers={"authorization": f"Bearer {self.personal_api_key}"}
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Does not actually block the request, but increments the counter
        response = self.client.get(
            f"/api/projects/{self.team.pk}/events", headers={"authorization": f"Bearer {self.personal_api_key}"}
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
                headers={"authorization": f"Bearer {self.personal_api_key}"},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # First user gets rate limited
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags", headers={"authorization": f"Bearer {self.personal_api_key}"}
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
        PersonalAPIKey.objects.create(
            label="X", user=new_user, secure_value=hash_key_value(new_personal_api_key), scopes=["*"]
        )
        self.client.force_login(new_user)

        incr_mock.reset_mock()

        # Second user gets rate limited after a single request
        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags", headers={"authorization": f"Bearer {new_personal_api_key}"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Create a new team
        new_team = create_team(organization=self.organization)
        new_user = create_user(email="test2@posthog.com", password="1234", organization=self.organization)
        new_personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X", user=new_user, secure_value=hash_key_value(new_personal_api_key), scopes=["*"]
        )

        incr_mock.reset_mock()

        # Requests to the new team are not rate limited
        response = self.client.get(
            f"/api/projects/{new_team.pk}/feature_flags", headers={"authorization": f"Bearer {new_personal_api_key}"}
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
                headers={"authorization": f"Bearer {new_personal_api_key}"},
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
                headers={"authorization": f"Bearer {self.personal_api_key}"},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(
            f"/api/organizations/{self.organization.pk}/plugins",
            headers={"authorization": f"Bearer {self.personal_api_key}"},
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
                headers={"authorization": f"Bearer {self.personal_api_key}"},
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
            response = self.client.get(
                "/e/?data={}".format(quote(json.dumps(data))), headers={"origin": "https://localhost"}
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
        with time_machine.travel("2022-04-01 12:34:45", tick=False) as frozen_time:
            with override_instance_config("RATE_LIMITING_ALLOW_LIST_TEAMS", f"{self.team.pk}"):
                with patch.object(
                    rate_limit,
                    "get_instance_setting",
                    wraps=models.instance_setting.get_instance_setting,
                ) as wrapped_get_instance_setting:
                    for _ in range(10):
                        self.client.get(
                            f"/api/projects/{self.team.pk}/feature_flags",
                            headers={"authorization": f"Bearer {self.personal_api_key}"},
                        )

                    assert wrapped_get_instance_setting.call_count == 1

                    frozen_time.shift(timedelta(seconds=65))
                    for _ in range(10):
                        self.client.get(
                            f"/api/projects/{self.team.pk}/feature_flags",
                            headers={"authorization": f"Bearer {self.personal_api_key}"},
                        )
                    assert wrapped_get_instance_setting.call_count == 2

    @patch("posthog.rate_limit.BurstRateThrottle.rate", new="5/minute")
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_allow_list_works_as_expected(self, rate_limit_enabled_mock, incr_mock):
        with time_machine.travel("2022-04-01 12:34:45", tick=False):
            with override_instance_config("RATE_LIMITING_ALLOW_LIST_TEAMS", f"{self.team.pk}"):
                for _ in range(10):
                    response = self.client.get(
                        f"/api/projects/{self.team.pk}/feature_flags",
                        headers={"authorization": f"Bearer {self.personal_api_key}"},
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

        # Mock UserRateThrottle.allow_request (the grandparent) to return False (rate limited)
        # We need to patch the grandparent so _AIThrottleBase.allow_request still executes
        with patch("rest_framework.throttling.UserRateThrottle.allow_request", return_value=False):
            result = throttle.allow_request(mock_request, mock_view)

            # Should return False (rate limited)
            self.assertFalse(result)

            # Should call report_user_action with correct parameters
            mock_report_user_action.assert_called_once_with(self.user, "ai burst rate limited", request=mock_request)

    @patch("posthog.rate_limit.report_user_action")
    def test_ai_sustained_rate_throttle_calls_report_user_action(self, mock_report_user_action):
        """Test that AISustainedRateThrottle calls report_user_action when rate limit is exceeded"""
        throttle = AISustainedRateThrottle()

        mock_request = Mock()
        mock_request.user = self.user
        mock_view = Mock()

        # Mock UserRateThrottle.allow_request (the grandparent) to return False (rate limited)
        # We need to patch the grandparent so _AIThrottleBase.allow_request still executes
        with patch("rest_framework.throttling.UserRateThrottle.allow_request", return_value=False):
            result = throttle.allow_request(mock_request, mock_view)

            # Should return False (rate limited)
            self.assertFalse(result)

            # Should call report_user_action with correct parameters
            mock_report_user_action.assert_called_once_with(
                self.user, "ai sustained rate limited", request=mock_request
            )

    @patch("posthog.rate_limit.report_user_action")
    def test_ai_research_burst_rate_throttle_calls_report_user_action(self, mock_report_user_action):
        """Test that AIResearchBurstRateThrottle calls report_user_action when rate limit is exceeded"""
        throttle = AIResearchBurstRateThrottle()

        mock_request = Mock()
        mock_request.user = self.user
        mock_view = Mock()

        # Mock UserRateThrottle.allow_request (the grandparent) to return False (rate limited)
        # We need to patch the grandparent so _AIThrottleBase.allow_request still executes
        with patch("rest_framework.throttling.UserRateThrottle.allow_request", return_value=False):
            result = throttle.allow_request(mock_request, mock_view)

            # Should return False (rate limited)
            self.assertFalse(result)

            # Should call report_user_action with correct parameters
            mock_report_user_action.assert_called_once_with(
                self.user, "ai research burst rate limited", request=mock_request
            )

    @patch("posthog.rate_limit.report_user_action")
    def test_ai_research_sustained_rate_throttle_calls_report_user_action(self, mock_report_user_action):
        """Test that AIResearchSustainedRateThrottle calls report_user_action when rate limit is exceeded"""
        throttle = AIResearchSustainedRateThrottle()

        mock_request = Mock()
        mock_request.user = self.user
        mock_view = Mock()

        # Mock UserRateThrottle.allow_request (the grandparent) to return False (rate limited)
        # We need to patch the grandparent so _AIThrottleBase.allow_request still executes
        with patch("rest_framework.throttling.UserRateThrottle.allow_request", return_value=False):
            result = throttle.allow_request(mock_request, mock_view)

            # Should return False (rate limited)
            self.assertFalse(result)

            # Should call report_user_action with correct parameters
            mock_report_user_action.assert_called_once_with(
                self.user, "ai research sustained rate limited", request=mock_request
            )

    def test_ai_research_burst_rate_throttle_has_correct_scope_and_rate(self):
        """Test that AIResearchBurstRateThrottle has correct scope and rate"""
        throttle = AIResearchBurstRateThrottle()
        self.assertEqual(throttle.scope, "ai_research_burst")
        self.assertEqual(throttle.rate, "3/minute")

    def test_ai_research_sustained_rate_throttle_has_correct_scope_and_rate(self):
        """Test that AIResearchSustainedRateThrottle has correct scope and rate"""
        throttle = AIResearchSustainedRateThrottle()
        self.assertEqual(throttle.scope, "ai_research_sustained")
        self.assertEqual(throttle.rate, "10/day")

    @patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False)
    @patch(
        "posthog.rate_limit.get_route_from_path", return_value="/api/environments/TEAM_ID/llm_prompts/name/PROMPT_NAME/"
    )
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_llm_prompt_publish_burst_throttle_limits_web_authenticated_requests(
        self, rate_limit_enabled_mock, incr_mock, route_mock, bypass_mock
    ):
        throttle = LLMPromptPublishBurstRateThrottle()
        mock_request = Mock()
        mock_request.user = Mock(is_authenticated=True, pk=self.user.pk)
        mock_request.path = f"/api/environments/{self.team.pk}/llm_prompts/name/my-prompt/"
        mock_view = Mock(team_id=self.team.pk)

        with (
            patch("posthog.rate_limit.PersonalAPIKeyAuthentication.find_key_with_source", return_value=None),
            patch("rest_framework.throttling.SimpleRateThrottle.allow_request", return_value=False),
        ):
            result = throttle.allow_request(mock_request, mock_view)

        self.assertFalse(result)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "llm_prompt_publish_burst",
                "rate": "30/minute",
                "route": "/api/environments/TEAM_ID/llm_prompts/name/PROMPT_NAME/",
                "hashed_personal_api_key": None,
            },
        )

    @patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False)
    @patch(
        "posthog.rate_limit.get_route_from_path", return_value="/api/environments/TEAM_ID/llm_prompts/name/PROMPT_NAME/"
    )
    @patch("posthog.rate_limit.statsd.incr")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_llm_prompt_publish_burst_throttle_limits_personal_api_key_requests(
        self, rate_limit_enabled_mock, incr_mock, route_mock, bypass_mock
    ):
        throttle = LLMPromptPublishBurstRateThrottle()
        mock_request = Mock()
        mock_request.user = Mock(is_authenticated=True, pk=self.user.pk)
        mock_request.path = f"/api/environments/{self.team.pk}/llm_prompts/name/my-prompt/"
        mock_view = Mock(team_id=self.team.pk)
        personal_api_key = "phx_test_personal_api_key"

        with (
            patch(
                "posthog.rate_limit.PersonalAPIKeyAuthentication.find_key_with_source",
                return_value=(personal_api_key, "header"),
            ),
            patch("rest_framework.throttling.SimpleRateThrottle.allow_request", return_value=False),
        ):
            result = throttle.allow_request(mock_request, mock_view)

        self.assertFalse(result)
        incr_mock.assert_any_call(
            "rate_limit_exceeded",
            tags={
                "team_id": self.team.pk,
                "scope": "llm_prompt_publish_burst",
                "rate": "30/minute",
                "route": "/api/environments/TEAM_ID/llm_prompts/name/PROMPT_NAME/",
                "hashed_personal_api_key": hash_key_value(personal_api_key),
            },
        )

    def test_remote_config_throttle_uses_default_rate_when_no_custom_limit(self):
        throttle = RemoteConfigThrottle()

        # Mock view and request
        mock_view = Mock()
        mock_request = Mock()

        with (
            patch("products.feature_flags.backend.api.feature_flag.REMOTE_CONFIG_RATE_LIMITS", {}),
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
            patch("products.feature_flags.backend.api.feature_flag.REMOTE_CONFIG_RATE_LIMITS", {}),
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
            patch("products.feature_flags.backend.api.feature_flag.REMOTE_CONFIG_RATE_LIMITS", {123: "1200/minute"}),
            patch.object(throttle, "safely_get_team_id_from_view", return_value=123),
            patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True),
        ):
            result = throttle.allow_request(mock_request, mock_view)

            self.assertTrue(result)
            # Should use custom rate
            self.assertEqual(throttle.rate, "1200/minute")
            self.assertEqual(throttle.num_requests, 1200)
            self.assertEqual(throttle.duration, 60)  # 1 minute in seconds

    def test_remote_config_team_throttle_uses_custom_rate_for_team(self):
        throttle = RemoteConfigProjectSecretApiKeyTeamThrottle()

        mock_view = Mock()
        mock_request = Mock()

        with (
            patch("products.feature_flags.backend.api.feature_flag.REMOTE_CONFIG_RATE_LIMITS", {123: "1200/minute"}),
            patch.object(throttle, "safely_get_team_id_from_view", return_value=123),
            patch.object(throttle.__class__.__bases__[0], "allow_request", return_value=True),
        ):
            result = throttle.allow_request(mock_request, mock_view)

            self.assertTrue(result)
            # The per-team throttle must apply the team's REMOTE_CONFIG_RATE_LIMITS override too, not
            # just the per-key throttle, otherwise a configured per-team cap silently has no effect.
            self.assertEqual(throttle.rate, "1200/minute")
            self.assertEqual(throttle.num_requests, 1200)
            self.assertEqual(throttle.duration, 60)

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

    def test_parse_rate_with_custom_minutes_format(self):
        """Test parsing custom format like '6/20minutes'"""
        throttle = rate_limit.UserOrEmailRateThrottle()
        num_requests, duration = throttle.parse_rate("6/20minutes")

        self.assertEqual(num_requests, 6)
        self.assertEqual(duration, 1200)  # 20 minutes * 60 seconds

    def test_health_issue_refresh_throttle_parses_15_minute_window(self):
        throttle = rate_limit.HealthIssueRefreshThrottle()
        num_requests, duration = throttle.parse_rate("1/15minutes")

        self.assertEqual(num_requests, 1)
        self.assertEqual(duration, 15 * 60)

    def test_health_issue_refresh_throttle_falls_back_to_default_parser(self):
        throttle = rate_limit.HealthIssueRefreshThrottle()
        num_requests, duration = throttle.parse_rate("5/hour")

        self.assertEqual(num_requests, 5)
        self.assertEqual(duration, 3600)


class _PSAKThrottleForTest(rate_limit.PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "test_psak"
    rate = "100/minute"


class TestPersonalOrProjectSecretApiKeyRateThrottle(SimpleTestCase):
    def _psak_request(self, key_id=1):
        auth = ProjectSecretAPIKeyAuthentication()
        auth.project_secret_api_key = Mock(id=key_id)
        return Mock(successful_authenticator=auth)

    @parameterized.expand(
        [
            ("base", _PSAKThrottleForTest),
            ("llm_prompt_fetch", rate_limit.LLMPromptFetchRateThrottle),
        ]
    )
    def test_psak_requests_do_not_bypass_throttle(self, _name, throttle_class):
        # PSAK carries no personal API key; the throttle must not let it through the
        # personal_api_key_only gate that PersonalApiKeyRateThrottle uses.
        throttle = throttle_class()
        request = self._psak_request()
        with patch.object(throttle, "_allow_request_internal", return_value=True) as spy:
            throttle.allow_request(request, Mock())
        spy.assert_called_once_with(request, ANY, personal_api_key_only=False)

    def test_non_psak_request_uses_personal_api_key_only_gate(self):
        throttle = _PSAKThrottleForTest()
        request = Mock(successful_authenticator=Mock())
        with patch.object(throttle, "_allow_request_internal", return_value=True) as spy:
            throttle.allow_request(request, Mock())
        spy.assert_called_once_with(ANY, ANY, personal_api_key_only=True)

    def test_psak_requests_use_per_key_cache_bucket(self):
        self.assertTrue(_PSAKThrottleForTest().get_cache_key(self._psak_request(key_id=42), Mock()).endswith("psak:42"))


class TestUserVerifyEmailThrottle(SimpleTestCase):
    CANONICAL_UUID = "12345678-1234-5678-1234-567812345678"

    def _request(self, uuid_value):
        return Mock(data={"uuid": uuid_value}, user=None)

    @parameterized.expand(
        [
            ("uppercase", "12345678-1234-5678-1234-567812345678".upper()),
            ("hyphen_free", "12345678123456781234567812345678"),
            ("brace_wrapped", "{12345678-1234-5678-1234-567812345678}"),
            ("urn_prefixed", "urn:uuid:12345678-1234-5678-1234-567812345678"),
        ]
    )
    def test_alternate_uuid_spellings_share_one_bucket(self, _name, variant):
        throttle = rate_limit.UserVerifyEmailThrottle()
        self.assertEqual(
            throttle.get_cache_key(self._request(self.CANONICAL_UUID), Mock()),
            throttle.get_cache_key(self._request(variant), Mock()),
        )

    def test_distinct_uuids_use_distinct_buckets(self):
        throttle = rate_limit.UserVerifyEmailThrottle()
        self.assertNotEqual(
            throttle.get_cache_key(self._request(self.CANONICAL_UUID), Mock()),
            throttle.get_cache_key(self._request("87654321-4321-8765-4321-876543218765"), Mock()),
        )

    def test_unparseable_uuid_falls_back_without_raising(self):
        throttle = rate_limit.UserVerifyEmailThrottle()
        self.assertIsNotNone(throttle.get_cache_key(self._request("not-a-uuid"), Mock()))


class TestAIObservabilitySummarizationRateThrottle(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    @parameterized.expand(
        [
            ("burst", rate_limit.AIObservabilitySummarizationBurstThrottle),
            ("sustained", rate_limit.AIObservabilitySummarizationSustainedThrottle),
            ("daily", rate_limit.AIObservabilitySummarizationDailyThrottle),
        ]
    )
    @patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False)
    @patch("posthog.rate_limit.PersonalAPIKeyAuthentication.find_key_with_source", return_value=None)
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_session_requests_are_rate_limited(
        self,
        _name: str,
        throttle_class: type[rate_limit.PersonalApiKeyRateThrottle],
        _rate_limit_enabled: Mock,
        _find_personal_api_key: Mock,
        _team_can_bypass: Mock,
    ) -> None:
        request = Mock(user=Mock(is_authenticated=True), path="/api/projects/1/llm_analytics/summarization/")
        view = Mock(team_id=1)

        with patch.object(throttle_class, "rate", "1/minute"):
            self.assertTrue(throttle_class().allow_request(request, view))
            self.assertFalse(throttle_class().allow_request(request, view))


class TestLeakedKeyReportThrottle(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    def test_scope_and_rate(self) -> None:
        throttle = rate_limit.LeakedKeyReportThrottle()
        self.assertEqual(throttle.scope, "leaked_key_report")
        self.assertEqual(throttle.rate, "10/minute")

    def test_limits_requests_per_ip(self) -> None:
        request = Mock(headers={}, META={"REMOTE_ADDR": "203.0.113.5"})
        other_request = Mock(headers={}, META={"REMOTE_ADDR": "203.0.113.6"})
        view = Mock()

        with patch.object(rate_limit.LeakedKeyReportThrottle, "rate", "1/minute"):
            self.assertTrue(rate_limit.LeakedKeyReportThrottle().allow_request(request, view))
            self.assertFalse(rate_limit.LeakedKeyReportThrottle().allow_request(request, view))
            self.assertTrue(rate_limit.LeakedKeyReportThrottle().allow_request(other_request, view))


class _PSAKTeamThrottleForTest(rate_limit.ProjectSecretApiKeyTeamRateThrottle):
    scope = "test_psak_team"
    rate = "100/minute"


class TestProjectSecretApiKeyTeamRateThrottle(SimpleTestCase):
    def _psak_request(self, team_id=7):
        auth = ProjectSecretAPIKeyAuthentication()
        auth.project_secret_api_key = Mock(team_id=team_id)
        return Mock(successful_authenticator=auth)

    def test_psak_request_is_throttled(self):
        throttle = _PSAKTeamThrottleForTest()
        with patch.object(throttle, "_allow_request_internal", return_value=True) as spy:
            throttle.allow_request(self._psak_request(), Mock())
        spy.assert_called_once_with(ANY, ANY, personal_api_key_only=False)

    def test_non_psak_request_bypasses(self):
        throttle = _PSAKTeamThrottleForTest()
        with patch.object(throttle, "_allow_request_internal") as spy:
            self.assertTrue(throttle.allow_request(Mock(successful_authenticator=Mock()), Mock()))
        spy.assert_not_called()

    def test_cache_key_is_keyed_per_team(self):
        self.assertIn("psak-team:7", _PSAKTeamThrottleForTest().get_cache_key(self._psak_request(team_id=7), Mock()))


_SendThrottle = rate_limit.PersonalOrProjectSecretApiKeyRateThrottle | rate_limit.ProjectSecretApiKeyTeamRateThrottle


class _TeamView(APIView):
    def __init__(self, team_id: int, throttle_classes: list[type[_SendThrottle]] | None = None) -> None:
        super().__init__()
        self.team_id = team_id
        self.throttle_classes = throttle_classes or []


class TestReserveUnits(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_instance_config("RATE_LIMIT_ENABLED", True))
        cache.clear()
        self._clear_policy_caches()
        self.token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="batch sends",
            secure_value=hash_key_value(self.token, mode="sha256"),
            scopes=["transactional_email:write"],
        )
        self.view = _TeamView(self.team.pk)
        self.cache_prefix = unique_key_prefix("test-reserve-units")

    def tearDown(self) -> None:
        cache.clear()
        self._clear_policy_caches()
        super().tearDown()

    def _clear_policy_caches(self) -> None:
        rate_limit.is_rate_limit_enabled.cache_clear()
        rate_limit.get_team_allow_list.cache_clear()

    def _request(self) -> Request:
        http_request = APIRequestFactory().post(
            "/api/messaging/send/email_batch/", headers={"authorization": f"Bearer {self.token}"}
        )
        return Request(http_request, authenticators=[ProjectSecretAPIKeyAuthentication()])

    def _singles_allowed(self, throttle_class: type[_SendThrottle], count: int) -> list[bool]:
        return [throttle_class().allow_request(self._request(), self.view) for _ in range(count)]

    def _reserve(self, throttle_classes: list[type[_SendThrottle]], units: int) -> None:
        rate_limit.reserve_units(
            [throttle_class() for throttle_class in throttle_classes], self._request(), self.view, units
        )

    def _send(self, throttle_classes: list[type[_SendThrottle]], recipients: int) -> str | None:
        request = self._request()
        view = _TeamView(self.team.pk, throttle_classes)
        try:
            view.check_throttles(request)
            rate_limit.reserve_units(
                [throttle_class() for throttle_class in throttle_classes], request, view, recipients - 1
            )
        except exceptions.Throttled as refusal:
            response = exception_handler(refusal, {"request": request})
            assert response is not None
            self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            return response.headers["Retry-After"]
        return None

    @parameterized.expand([("per_key", _PSAKThrottleForTest), ("per_team", _PSAKTeamThrottleForTest)])
    def test_units_and_single_requests_spend_one_budget(self, _name, throttle_class):
        with patch.object(throttle_class, "rate", "5/minute"):
            self._reserve([throttle_class], 3)
            self.assertEqual(self._singles_allowed(throttle_class, 3), [True, True, False])
            with self.assertRaises(exceptions.Throttled):
                self._reserve([throttle_class], 1)

    @parameterized.expand([("over_the_limit", 4), ("at_the_limit_before_its_drf_unit", 3)])
    def test_a_reservation_no_limit_can_hold_is_refused_without_a_retry_wait(self, _name, units):
        with (
            patch.object(_PSAKThrottleForTest, "rate", "5/minute"),
            patch.object(_PSAKTeamThrottleForTest, "rate", "3/minute"),
        ):
            with self.assertRaises(exceptions.Throttled) as refusal:
                self._reserve([_PSAKThrottleForTest, _PSAKTeamThrottleForTest], units)
            response = exception_handler(refusal.exception, {"request": self._request()})

            assert response is not None
            self.assertNotIn("Retry-After", response.headers)
            self.assertEqual(self._singles_allowed(_PSAKThrottleForTest, 6), [True] * 5 + [False])

    def test_a_refused_reservation_charges_none_of_the_throttles(self):
        with (
            patch.object(_PSAKTeamThrottleForTest, "rate", "4/minute"),
            patch.object(_PSAKThrottleForTest, "rate", "5/minute"),
        ):
            self._singles_allowed(_PSAKThrottleForTest, 3)
            with self.assertRaises(exceptions.Throttled):
                self._reserve([_PSAKTeamThrottleForTest, _PSAKThrottleForTest], 3)

            self.assertEqual(self._singles_allowed(_PSAKTeamThrottleForTest, 5), [True, True, True, True, False])

    @parameterized.expand(
        [
            ("the_refusing_scope_needs_room_for_the_retry_unit", "3/minute", "4/minute", [0, 20], 30, "50"),
            ("an_admitting_scope_has_no_room_for_the_retry", "2/minute", "4/hour", [0, 100], 130, "3470"),
            ("skewed_worker_clocks_left_the_history_out_of_order", "4/minute", "100/minute", [1, 2, 0], 30, "31"),
        ]
    )
    def test_a_retry_at_the_advertised_wait_fits(self, _name, key_rate, team_rate, singles_at, batch_at, retry_after):
        with (
            patch.object(_PSAKThrottleForTest, "rate", key_rate),
            patch.object(_PSAKTeamThrottleForTest, "rate", team_rate),
            time_machine.travel("2026-01-01T00:00:00Z", tick=False) as clock,
        ):
            throttle_classes: list[type[_SendThrottle]] = [
                _PSAKThrottleForTest,
                _PSAKTeamThrottleForTest,
            ]
            elapsed = 0
            for second in [*singles_at, batch_at]:
                clock.shift(second - elapsed)
                elapsed = second
                outcome = self._send(throttle_classes, 2 if second == batch_at else 1)

            self.assertEqual(outcome, retry_after)
            clock.shift(int(retry_after))
            self.assertIsNone(self._send(throttle_classes, 2))

    def test_a_single_send_refused_at_the_advertised_wait_is_admitted_after_it(self):
        with (
            patch.object(TransactionalEmailBurstThrottle, "rate", "4/minute"),
            time_machine.travel("2026-01-01T00:00:00Z", tick=False) as clock,
        ):
            for shift in (1, 1, -2, 30):
                clock.shift(shift)
                self.assertIsNone(self._send([TransactionalEmailBurstThrottle], 1))
            retry_after = self._send([TransactionalEmailBurstThrottle], 1)
            assert retry_after is not None
            clock.shift(int(retry_after))
            retried = self._send([TransactionalEmailBurstThrottle], 1)

        self.assertEqual(retry_after, "30")
        self.assertIsNone(retried)

    def test_a_reused_throttle_charges_nothing_left_from_a_refused_reservation(self):
        with (
            patch.object(_PSAKThrottleForTest, "rate", "3/minute"),
            patch.object(_PSAKTeamThrottleForTest, "rate", "5/minute"),
        ):
            self._singles_allowed(_PSAKThrottleForTest, 2)
            throttles: list[_SendThrottle] = [_PSAKThrottleForTest(), _PSAKTeamThrottleForTest()]
            with self.assertRaises(exceptions.Throttled):
                rate_limit.reserve_units(throttles, self._request(), self.view, 2)

            with override_instance_config("RATE_LIMIT_ENABLED", False):
                self._clear_policy_caches()
                rate_limit.reserve_units(throttles, self._request(), self.view, 2)

            self._clear_policy_caches()
            self.assertEqual(self._singles_allowed(_PSAKTeamThrottleForTest, 6), [True, True, True, True, True, False])

    def test_a_reused_throttle_advertises_no_wait_left_from_a_refused_reservation(self):
        with (
            patch.object(_PSAKThrottleForTest, "rate", "3/minute"),
            patch.object(_PSAKTeamThrottleForTest, "rate", "3/hour"),
            time_machine.travel("2026-01-01T00:00:00Z", tick=False),
        ):
            self._singles_allowed(_PSAKTeamThrottleForTest, 2)
            throttles: list[_SendThrottle] = [_PSAKThrottleForTest(), _PSAKTeamThrottleForTest()]
            with self.assertRaises(exceptions.Throttled):
                rate_limit.reserve_units(throttles, self._request(), self.view, 2)
            self._singles_allowed(_PSAKThrottleForTest, 2)
            unreachable = RedisCache("redis://127.0.0.1:1/0", {})

            with (
                patch.object(_PSAKTeamThrottleForTest, "cache", unreachable),
                patch.object(_PSAKTeamThrottleForTest, "primary_cache", unreachable),
            ):
                with self.assertRaises(exceptions.Throttled) as refusal:
                    rate_limit.reserve_units(throttles, self._request(), self.view, 2)

            response = exception_handler(refusal.exception, {"request": self._request()})
            assert response is not None
            self.assertEqual(response.headers["Retry-After"], "60")

    def _lagging_reader_caches(self, primary_location: str | None = None) -> dict[str, Any]:
        return lagging_reader_caches(self.cache_prefix, primary_location)

    def test_a_reservation_counts_the_charge_a_lagging_reader_has_not_seen(self):
        now = time.time()
        with (
            override_settings(CACHES=self._lagging_reader_caches()),
            patch.object(_PSAKThrottleForTest, "rate", "2/minute"),
            patch.object(_PSAKThrottleForTest, "timer", lambda _throttle: now),
        ):
            redis_cache = caches["default"]
            assert isinstance(redis_cache, RedisCache)
            key = _PSAKThrottleForTest().get_cache_key(self._request(), self.view)
            primary_client, reader_client = clients = [
                redis_cache.client.get_client(write=True),
                redis_cache.client.get_client(write=False),
            ]
            try:
                self.assertEqual(self._singles_allowed(_PSAKThrottleForTest, 1), [True])
                redis_cache.set(key, redis_cache.get(key, client=primary_client), 60, client=reader_client)
                retry_after = self._send([_PSAKThrottleForTest], 2)
            finally:
                for client in clients:
                    redis_cache.delete(key, client=client)

        self.assertEqual(retry_after, "60")

    @parameterized.expand(
        [
            ("burst", TransactionalEmailBurstThrottle, "60"),
            ("sustained", TransactionalEmailSustainedThrottle, "60"),
            ("team_burst", TransactionalEmailTeamBurstThrottle, "60"),
            ("team_sustained", TransactionalEmailTeamSustainedThrottle, "60"),
            ("a_throttle_that_reads_the_replica", _PSAKThrottleForTest, None),
        ]
    )
    def test_a_single_after_a_batch_counts_the_charges_a_lagging_reader_has_not_seen(
        self, _name, throttle_class, retry_after
    ):
        now = time.time()
        with (
            override_settings(CACHES=self._lagging_reader_caches()),
            patch.object(throttle_class, "rate", "5/minute"),
            patch.object(throttle_class, "timer", lambda _throttle: now),
        ):
            redis_cache = caches["default"]
            assert isinstance(redis_cache, RedisCache)
            key = throttle_class().get_cache_key(self._request(), self.view)
            primary_client = redis_cache.client.get_client(write=True)
            reader_client = redis_cache.client.get_client(write=False)
            try:
                self.assertIsNone(self._send([throttle_class], 1))
                redis_cache.set(key, redis_cache.get(key, client=primary_client), 60, client=reader_client)
                self.assertIsNone(self._send([throttle_class], 4))
                outcome = self._send([throttle_class], 1)
            finally:
                for client in (primary_client, reader_client):
                    redis_cache.delete(key, client=client)

        self.assertEqual(outcome, retry_after)

    def test_a_refusal_is_counted(self):
        route = rate_limit.get_route_from_path("/api/messaging/send/email_batch/")
        labels = {"team_id": str(self.team.pk), "scope": _PSAKThrottleForTest.scope, "path": route, "route": route}
        before = REGISTRY.get_sample_value("rate_limit_exceeded_total", labels) or 0

        with patch.object(_PSAKThrottleForTest, "rate", "3/minute"), self.assertRaises(exceptions.Throttled):
            self._reserve([_PSAKThrottleForTest], 4)

        self.assertEqual(REGISTRY.get_sample_value("rate_limit_exceeded_total", labels), before + 1)

    @parameterized.expand(
        [
            ("rate_limiting_off", "RATE_LIMIT_ENABLED", False),
            ("team_on_the_bypass_list", "RATE_LIMITING_ALLOW_LIST_TEAMS", "team"),
        ]
    )
    def test_an_over_budget_reservation_passes_when_the_settings_say_not_to_refuse(self, _name, setting, value):
        with override_instance_config(setting, str(self.team.pk) if value == "team" else value):
            self._clear_policy_caches()
            with patch.object(_PSAKThrottleForTest, "rate", "3/minute"):
                self._reserve([_PSAKThrottleForTest], 4)

        self._clear_policy_caches()
        with patch.object(_PSAKThrottleForTest, "rate", "3/minute"):
            self.assertEqual(self._singles_allowed(_PSAKThrottleForTest, 4), [True, True, True, False])

    def _redis_cache(self, location: str) -> RedisCache:
        return RedisCache(location, {"KEY_PREFIX": self.cache_prefix})

    @contextmanager
    def _redis_that_refuses_writes(self) -> Iterator[RedisCache]:
        admin = Redis.from_url(settings.REDIS_URL)
        user, password = unique_key_prefix("read-only"), uuid4().hex
        admin.acl_setuser(user, enabled=True, passwords=[f"+{password}"], keys=["*"], categories=["+@all", "-@write"])
        primary = urlsplit(settings.REDIS_URL)
        credentials = f"{user}:{password}@{primary.hostname or 'localhost'}:{primary.port or 6379}"
        try:
            yield self._redis_cache(f"{primary.scheme}://{credentials}{primary.path}?{primary.query}")
        finally:
            admin.acl_deluser(user)
            admin.close()

    @parameterized.expand(
        [
            ("read_fails_open_over_budget", "unreachable", 2, [True, False]),
            ("write_fails_without_refusing", "refuses_writes", 0, [True, True, True, False]),
        ]
    )
    def test_a_reservation_passes_when_redis_fails(self, _name, failure, spent, singles_after):
        shared = self._redis_cache(settings.REDIS_URL)
        failing = (
            nullcontext(RedisCache("redis://127.0.0.1:1/0", {}))
            if failure == "unreachable"
            else self._redis_that_refuses_writes()
        )
        with (
            patch.object(_PSAKThrottleForTest, "rate", "3/minute"),
            patch.object(_PSAKThrottleForTest, "cache", shared),
        ):
            try:
                self._singles_allowed(_PSAKThrottleForTest, spent)
                with (
                    failing as failing_cache,
                    patch.object(_PSAKThrottleForTest, "cache", failing_cache),
                    patch.object(_PSAKThrottleForTest, "primary_cache", failing_cache),
                ):
                    self._reserve([_PSAKThrottleForTest], 2)

                self.assertEqual(self._singles_allowed(_PSAKThrottleForTest, len(singles_after)), singles_after)
            finally:
                shared.delete_pattern("*")

    @contextmanager
    def _stalled_redis(self) -> Iterator[tuple[str, list[list[bytes]]]]:
        reads: list[list[bytes]] = []
        listener = socket.create_server(("127.0.0.1", 0))
        listener.settimeout(0.05)
        stopped = threading.Event()

        def answer(connection: socket.socket) -> None:
            with connection, connection.makefile("rb") as stream:
                while header := stream.readline():
                    command = [stream.read(int(stream.readline()[1:]) + 2)[:-2] for _ in range(int(header[1:]))]
                    if command[0].upper() == b"GET":
                        reads.append(command)
                    else:
                        connection.sendall(b"+OK\r\n")

        def serve() -> None:
            while not stopped.is_set():
                with suppress(TimeoutError):
                    threading.Thread(target=answer, args=(listener.accept()[0],), daemon=True).start()

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        port = listener.getsockname()[1]
        try:
            yield f"redis://127.0.0.1:{port}/0?socket_connect_timeout=300&socket_timeout=300&retry_on_timeout=1", reads
        finally:
            stopped.set()
            server.join()
            listener.close()

    @parameterized.expand([("unreachable",), ("stalled",)])
    def test_a_send_reads_the_replica_when_the_primary_read_fails(self, failure):
        now = time.time()
        reader_only = self._lagging_reader_caches(
            primary_location=self._lagging_reader_caches()["default"]["LOCATION"][1]
        )
        failing_primary: AbstractContextManager[tuple[str, list[list[bytes]]]] = (
            nullcontext(("redis://127.0.0.1:1/0", [])) if failure == "unreachable" else self._stalled_redis()
        )
        with (
            patch.object(TransactionalEmailBurstThrottle, "rate", "3/minute"),
            patch.object(TransactionalEmailBurstThrottle, "timer", lambda _throttle: now),
        ):
            try:
                with override_settings(CACHES=reader_only):
                    self.assertEqual(
                        self._singles_allowed(TransactionalEmailBurstThrottle, 4), [True, True, True, False]
                    )
                with (
                    failing_primary as (primary_location, stalled_reads),
                    override_settings(CACHES=self._lagging_reader_caches(primary_location=primary_location)),
                ):
                    redis_cache = caches["default"]
                    assert isinstance(redis_cache, RedisCache)
                    redis_cache.client.get_client(write=True)
                    outcome = self._send([TransactionalEmailBurstThrottle], 1)
                    reads_sent = len(stalled_reads)
            finally:
                with override_settings(CACHES=reader_only):
                    caches["default"].delete(
                        TransactionalEmailBurstThrottle().get_cache_key(self._request(), self.view)
                    )

        self.assertEqual(outcome, "60")
        self.assertEqual(reads_sent, 0 if failure == "unreachable" else 1)

    def test_a_send_without_a_replica_passes_when_the_primary_stalls(self):
        with self._stalled_redis() as (stalled, _reads):
            default = {"BACKEND": "django_redis.cache.RedisCache", "LOCATION": stalled, "KEY_PREFIX": self.cache_prefix}
            with (
                override_settings(CACHES={"default": default, "throttle_history": throttle_history_cache(default)}),
                patch.object(TransactionalEmailBurstThrottle, "rate", "3/minute"),
            ):
                outcome = self._send([TransactionalEmailBurstThrottle], 1)

        self.assertIsNone(outcome)

    @parameterized.expand([("single", 1), ("batch", 3)])
    def test_a_send_admitted_from_the_replica_leaves_the_primary_charges_alone(self, _name, recipients):
        now = time.time()
        lagging = self._lagging_reader_caches()
        history_unreachable = {
            **lagging,
            "throttle_history": {**lagging["throttle_history"], "LOCATION": "redis://127.0.0.1:1/0"},
        }
        with (
            patch.object(TransactionalEmailBurstThrottle, "rate", "4/minute"),
            patch.object(TransactionalEmailBurstThrottle, "timer", lambda _throttle: now),
            override_settings(CACHES=lagging),
        ):
            redis_cache = caches["default"]
            assert isinstance(redis_cache, RedisCache)
            key = TransactionalEmailBurstThrottle().get_cache_key(self._request(), self.view)
            primary_client, reader_client = clients = [
                redis_cache.client.get_client(write=True),
                redis_cache.client.get_client(write=False),
            ]
            try:
                with override_settings(
                    CACHES=self._lagging_reader_caches(primary_location=lagging["default"]["LOCATION"][1])
                ):
                    self.assertIsNone(self._send([TransactionalEmailBurstThrottle], 1))
                self.assertEqual(self._singles_allowed(TransactionalEmailBurstThrottle, 4), [True] * 4)
                with override_settings(CACHES=history_unreachable):
                    admitted_from_the_replica = self._send([TransactionalEmailBurstThrottle], recipients)
                outcome = self._send([TransactionalEmailBurstThrottle], 1)
            finally:
                for client in clients:
                    redis_cache.delete(key, client=client)

        self.assertIsNone(admitted_from_the_replica)
        self.assertEqual(outcome, "60")


class TestWidgetTeamPollWriteThrottleSplit(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    def test_exhausted_poll_bucket_does_not_block_write(self) -> None:
        request = Mock(headers={"X-Conversations-Token": "widget-token"}, path="/api/conversations/v1/widget/tickets")
        view = Mock()
        with patch.object(rate_limit.WidgetTeamPollThrottle, "rate", "1/minute"):
            poll = rate_limit.WidgetTeamPollThrottle()
            self.assertTrue(poll.allow_request(request, view))
            self.assertFalse(poll.allow_request(request, view))
        self.assertTrue(rate_limit.WidgetTeamWriteThrottle().allow_request(request, view))

    @parameterized.expand(
        [
            ("user_burst", rate_limit.WidgetUserBurstThrottle),
            ("team_poll", rate_limit.WidgetTeamPollThrottle),
        ]
    )
    def test_exhausted_bucket_is_counted_by_scope_and_team(
        self, _name: str, throttle_class: type[rate_limit.WidgetUserBurstThrottle | rate_limit.WidgetTeamPollThrottle]
    ) -> None:
        path = "/api/conversations/v1/widget/tickets"
        request = Mock(
            headers={"X-Conversations-Token": "widget-token"},
            auth=Mock(id=7),
            path=path,
            data={},
            query_params={"widget_session_id": "session"},
        )
        route = rate_limit.get_route_from_path(path)
        labels = {"team_id": "7", "scope": throttle_class.scope, "path": route, "route": route}
        before = REGISTRY.get_sample_value("rate_limit_exceeded_total", labels) or 0

        with patch.object(throttle_class, "rate", "1/minute"):
            throttle = throttle_class()
            self.assertTrue(throttle.allow_request(request, Mock()))
            self.assertFalse(throttle.allow_request(request, Mock()))

        self.assertEqual(REGISTRY.get_sample_value("rate_limit_exceeded_total", labels), before + 1)
