from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

import requests
from parameterized import parameterized

from posthog.helpers.email_utils import (
    ESP_SUPPRESSION_CACHE_TTL_IN_SECONDS,
    ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS,
    EmailLookupHandler,
    EmailNormalizer,
    EmailValidationHelper,
    ESPSuppressionReason,
    _get_esp_suppression_cache_key,
    check_esp_suppression,
)
from posthog.models.user import User


class TestEmailNormalizer(TestCase):
    def test_normalize(self):
        """Test that email normalization works correctly."""
        test_cases = [
            ("test@EXAMPLE.COM", "test@example.com"),
            ("TEST@example.com", "test@example.com"),
            ("Test@Example.Com", "test@example.com"),
            ("USER@GMAIL.COM", "user@gmail.com"),
            ("user@gmail.com", "user@gmail.com"),
            ("User.Name+Tag@Example.ORG", "user.name+tag@example.org"),
            ("", ""),
        ]

        for input_email, expected in test_cases:
            with self.subTest(input_email=input_email):
                result = EmailNormalizer.normalize(input_email)
                self.assertEqual(result, expected)


class TestEmailLookupHandler(TestCase):
    def test_get_user_by_email_no_user(self):
        """Test getting user by email when none exists."""
        result = EmailLookupHandler.get_user_by_email("nonexistent@example.com")
        self.assertIsNone(result)

    def test_get_user_by_email_case_insensitive(self):
        """Test getting user by email with case variations."""
        user = User(email="Test@Example.COM", first_name="Test", last_name="User")
        user.set_password("testpass123")
        user.save()

        try:
            test_variations = ["test@example.com", "Test@Example.COM", "TEST@EXAMPLE.COM", "test@EXAMPLE.com"]

            for email_variation in test_variations:
                with self.subTest(email=email_variation):
                    found_user = EmailLookupHandler.get_user_by_email(email_variation)
                    self.assertIsNotNone(found_user)
                    if found_user is not None:
                        self.assertEqual(found_user.id, user.id)
        finally:
            user.delete()


class TestEmailValidationHelper(TestCase):
    def test_user_exists_no_user(self):
        """Test checking if user exists when none exists."""
        result = EmailValidationHelper.user_exists("nonexistent@example.com")
        self.assertFalse(result)

    def test_user_exists_with_user(self):
        """Test checking if user exists when user exists."""
        user = User.objects.create_user(email="TestExists@Example.COM", password="testpass123", first_name="Test")

        try:
            test_variations = [
                "testexists@example.com",
                "TestExists@Example.COM",
                "TESTEXISTS@EXAMPLE.COM",
                "testexists@EXAMPLE.com",
            ]

            for email_variation in test_variations:
                with self.subTest(email=email_variation):
                    result = EmailValidationHelper.user_exists(email_variation)
                    self.assertTrue(result)
        finally:
            user.delete()


class TestESPSuppressionCheck(SimpleTestCase):
    def test_returns_not_suppressed_for_empty_email(self):
        result = check_esp_suppression("")

        self.assertFalse(result.is_suppressed)
        self.assertEqual(result.reason, ESPSuppressionReason.EMPTY_EMAIL)

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.cache")
    def test_cache_hit_returns_cached_value_without_api_call(self, mock_cache):
        mock_cache.get.return_value = True

        with patch("posthog.helpers.email_utils.requests.get") as mock_get:
            result = check_esp_suppression("test@example.com")

            mock_get.assert_not_called()
            self.assertTrue(result.is_suppressed)
            self.assertTrue(result.from_cache)

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.cache")
    @patch("posthog.helpers.email_utils.requests.get")
    def test_cache_miss_triggers_api_call_and_caches_result(self, mock_get, mock_cache):
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "category": "bounces",
            "suppressions": [{"email": "test@example.com", "reason": "hard bounce"}],
        }
        mock_get.return_value = mock_response

        result = check_esp_suppression("test@example.com")

        mock_get.assert_called_once()
        mock_cache.set.assert_called_once()
        self.assertTrue(result.is_suppressed)
        self.assertFalse(result.from_cache)

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.cache")
    @patch("posthog.helpers.email_utils.requests.get")
    def test_cache_set_with_correct_ttl(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"suppressions": None}
        mock_get.return_value = mock_response

        check_esp_suppression("test@example.com")

        call_args = mock_cache.set.call_args
        self.assertEqual(call_args[0][2], ESP_SUPPRESSION_CACHE_TTL_IN_SECONDS)

    @parameterized.expand(
        [
            ("timeout", requests.Timeout(), True, ESPSuppressionReason.API_FAILURE_FALLBACK),
            ("network_error", requests.ConnectionError(), True, ESPSuppressionReason.API_FAILURE_FALLBACK),
            ("500_error", None, True, ESPSuppressionReason.API_FAILURE_FALLBACK),
            ("429_rate_limited", None, False, None),
        ]
    )
    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.cache")
    @patch("posthog.helpers.email_utils.requests.get")
    def test_api_failures_use_fallback_to_allow_login(
        self, name, exception, expected_suppressed, expected_reason, mock_get, mock_cache
    ):
        mock_cache.get.return_value = None

        if exception:
            mock_get.side_effect = exception
        else:
            mock_response = MagicMock()
            mock_response.status_code = 500 if expected_suppressed else 429
            mock_response.text = "Error"
            mock_get.return_value = mock_response

        result = check_esp_suppression("test@example.com")

        self.assertEqual(result.is_suppressed, expected_suppressed)
        self.assertFalse(result.from_cache)
        self.assertEqual(result.reason, expected_reason)

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    def test_email_hash_is_case_insensitive_and_anonymized(self):
        key_lower = _get_esp_suppression_cache_key("test@example.com")
        key_upper = _get_esp_suppression_cache_key("TEST@EXAMPLE.COM")
        key_other = _get_esp_suppression_cache_key("other@example.com")

        self.assertTrue(key_lower.startswith("email_mfa_suppressed:"))
        self.assertEqual(key_lower, key_upper)
        self.assertNotEqual(key_lower, key_other)
        self.assertNotIn("@", key_lower)

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.cache")
    @patch("posthog.helpers.email_utils.requests.get")
    def test_api_error_caches_error_state_with_short_ttl(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_get.side_effect = requests.Timeout()

        check_esp_suppression("test@example.com")

        # Verify error was cached with short TTL
        set_calls = list(mock_cache.set.call_args_list)
        error_cache_call = [c for c in set_calls if "error" in c[0][0]]
        self.assertEqual(len(error_cache_call), 1)
        self.assertEqual(error_cache_call[0][0][2], ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS)

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.cache")
    @patch("posthog.helpers.email_utils.requests.get")
    def test_429_rate_limit_caches_with_short_ttl(self, mock_get, mock_cache):
        mock_cache.get.return_value = None
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        check_esp_suppression("test@example.com")

        # Verify result was cached with short TTL (not the default 1 day)
        call_args = mock_cache.set.call_args
        self.assertEqual(call_args[0][2], ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS)

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.cache")
    def test_cached_error_returns_fallback_without_api_call(self, mock_cache):
        # Simulate: normal cache miss, but error cache hit
        def cache_get_side_effect(key):
            if "error" in key:
                return True
            return None

        mock_cache.get.side_effect = cache_get_side_effect

        with patch("posthog.helpers.email_utils.requests.get") as mock_get:
            result = check_esp_suppression("test@example.com")

            mock_get.assert_not_called()
            self.assertTrue(result.is_suppressed)
            self.assertTrue(result.from_cache)
            self.assertEqual(result.reason, ESPSuppressionReason.API_FAILURE_FALLBACK)


class TestESPSuppressionAnalytics(SimpleTestCase):
    @parameterized.expand(
        [
            ("success_cache_suppressed", True, "suppressed", "success_cache", False, None, None),
            ("success_cache_not_suppressed", False, "not_suppressed", "success_cache", False, None, None),
            ("error_cache", None, "api_failure_fallback", "error_cache", False, None, None),
            ("api_200_suppressed", None, "suppressed", None, True, 200, None),
            ("api_200_not_suppressed", None, "not_suppressed", None, True, 200, None),
            ("api_429", None, "not_suppressed", None, True, 429, None),
            ("api_500", None, "api_failure_fallback", None, True, 500, "http_error"),
            ("api_timeout", None, "api_failure_fallback", None, True, None, "timeout"),
        ]
    )
    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.posthoganalytics.capture")
    @patch("posthog.helpers.email_utils.cache")
    @patch("posthog.helpers.email_utils.requests.get")
    def test_analytics_captured_for_each_scenario(
        self,
        name,
        cached_value,
        expected_outcome,
        expected_cache_type,
        expected_api_called,
        expected_status_code,
        expected_error_type,
        mock_get,
        mock_cache,
        mock_capture,
    ):
        def cache_get_side_effect(key):
            if "error" in key:
                return True if expected_cache_type == "error_cache" else None
            return cached_value if expected_cache_type == "success_cache" else None

        mock_cache.get.side_effect = cache_get_side_effect

        if expected_api_called:
            if expected_error_type == "timeout":
                mock_get.side_effect = requests.Timeout()
            else:
                mock_response = MagicMock()
                mock_response.status_code = expected_status_code or 200
                mock_response.text = "error"
                if expected_status_code == 200:
                    if expected_outcome == "suppressed":
                        mock_response.json.return_value = {
                            "category": "bounces",
                            "suppressions": [{"email": "test@example.com", "reason": "hard bounce"}],
                        }
                    else:
                        mock_response.json.return_value = {"suppressions": None}
                mock_get.return_value = mock_response

        check_esp_suppression("test@example.com")

        mock_capture.assert_called()
        call_kwargs = mock_capture.call_args[1]
        self.assertEqual(call_kwargs["event"], "esp_suppression_check")
        self.assertEqual(call_kwargs["properties"]["outcome"], expected_outcome)
        self.assertEqual(call_kwargs["properties"]["cache_type"], expected_cache_type)
        self.assertEqual(call_kwargs["properties"]["api_called"], expected_api_called)
        if expected_status_code:
            self.assertEqual(call_kwargs["properties"]["api_status_code"], expected_status_code)
        if expected_error_type:
            self.assertEqual(call_kwargs["properties"]["error_type"], expected_error_type)
