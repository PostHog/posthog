from typing import cast

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

import requests
from parameterized import parameterized
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from posthog.helpers.email_utils import (
    ESP_SUPPRESSION_CACHE_TTL_IN_SECONDS,
    ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS,
    EmailLookupHandler,
    EmailNormalizer,
    EmailValidationHelper,
    ESPSuppressionReason,
    _get_esp_suppression_cache_key,
    check_esp_suppression,
    validate_display_name,
    validate_message_body,
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
                assert result == expected


class TestEmailLookupHandler(TestCase):
    def test_get_user_by_email_no_user(self):
        """Test getting user by email when none exists."""
        result = EmailLookupHandler.get_user_by_email("nonexistent@example.com")
        assert result is None

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
                    assert found_user is not None
                    if found_user is not None:
                        assert found_user.id == user.id
        finally:
            user.delete()


class TestEmailValidationHelper(TestCase):
    def test_user_exists_no_user(self):
        """Test checking if user exists when none exists."""
        result = EmailValidationHelper.user_exists("nonexistent@example.com")
        assert not result

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
                    assert result
        finally:
            user.delete()


class TestESPSuppressionCheck(SimpleTestCase):
    def test_returns_not_suppressed_for_empty_email(self):
        result = check_esp_suppression("")

        assert not result.is_suppressed
        assert result.reason == ESPSuppressionReason.EMPTY_EMAIL

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    @patch("posthog.helpers.email_utils.cache")
    def test_cache_hit_returns_cached_value_without_api_call(self, mock_cache):
        mock_cache.get.return_value = True

        with patch("posthog.helpers.email_utils.requests.get") as mock_get:
            result = check_esp_suppression("test@example.com")

            mock_get.assert_not_called()
            assert result.is_suppressed
            assert result.from_cache

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
        assert result.is_suppressed
        assert not result.from_cache

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
        assert call_args[0][2] == ESP_SUPPRESSION_CACHE_TTL_IN_SECONDS

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

        assert result.is_suppressed == expected_suppressed
        assert not result.from_cache
        assert result.reason == expected_reason

    @override_settings(CUSTOMER_IO_API_KEY="test-app-api-key")
    def test_email_hash_is_case_insensitive_and_anonymized(self):
        key_lower = _get_esp_suppression_cache_key("test@example.com")
        key_upper = _get_esp_suppression_cache_key("TEST@EXAMPLE.COM")
        key_other = _get_esp_suppression_cache_key("other@example.com")

        assert key_lower.startswith("email_mfa_suppressed:")
        assert key_lower == key_upper
        assert key_lower != key_other
        assert "@" not in key_lower

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
        assert len(error_cache_call) == 1
        assert error_cache_call[0][0][2] == ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS

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
        assert call_args[0][2] == ESP_SUPPRESSION_ERROR_CACHE_TTL_IN_SECONDS

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
            assert result.is_suppressed
            assert result.from_cache
            assert result.reason == ESPSuppressionReason.API_FAILURE_FALLBACK


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
        assert call_kwargs["event"] == "esp_suppression_check"
        assert call_kwargs["properties"]["outcome"] == expected_outcome
        assert call_kwargs["properties"]["cache_type"] == expected_cache_type
        assert call_kwargs["properties"]["api_called"] == expected_api_called
        if expected_status_code:
            assert call_kwargs["properties"]["api_status_code"] == expected_status_code
        if expected_error_type:
            assert call_kwargs["properties"]["error_type"] == expected_error_type


class TestValidateDisplayName(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", "Marius", "Marius"),
            ("two_part", "Marius Andra", "Marius Andra"),
            ("emoji", "Marius 🦔", "Marius 🦔"),
            ("apostrophe", "O'Brien", "O'Brien"),
            ("hyphen", "Jean-Luc", "Jean-Luc"),
            ("unicode", "Михаил", "Михаил"),
            ("amp", "Ben & Jerry's", "Ben & Jerry's"),
            ("www_midword", "Wwwilliam", "Wwwilliam"),
            ("dot_acronym", "St. John's, Inc.", "St. John's, Inc."),
            ("trims", "   Marius   ", "Marius"),
            ("empty", "", ""),
            ("whitespace_only", "   ", ""),
        ]
    )
    def test_accepts(self, _name: str, value: str, expected: str) -> None:
        assert validate_display_name(value) == expected

    def test_none_passes_through(self) -> None:
        assert validate_display_name(None) is None

    @parameterized.expand(
        [
            ("https", "Visit https://evil.com", "invalid_url"),
            ("http", "http://phish.me", "invalid_url"),
            ("ftp", "grab ftp://phish.me", "invalid_url"),
            ("file", "see file:///etc/passwd", "invalid_url"),
            ("custom_scheme", "go slack://hack", "invalid_url"),
            ("www", "www.scam.io", "invalid_url"),
            ("full_payload", "GET A GIFT https://hicerento.reamaze.com", "invalid_url"),
            ("newline", "Line1\nLine2", "invalid_control_char"),
            ("carriage_return", "foo\rbar", "invalid_control_char"),
            ("tab", "foo\tbar", "invalid_control_char"),
            ("null", "foo\x00bar", "invalid_control_char"),
            ("del", "foo\x7fbar", "invalid_control_char"),
            ("line_separator", "foo\u2028bar", "invalid_control_char"),
            ("paragraph_separator", "foo\u2029bar", "invalid_control_char"),
            ("next_line", "foo\u0085bar", "invalid_control_char"),
            ("www_embedded", "myname www.scam.io", "invalid_url"),
            ("bare_domain", "join evil.com now", "invalid_url"),
            ("bare_domain_at_start", "Acme.com", "invalid_url"),
            ("javascript_scheme", "click javascript:alert(1)", "invalid_url"),
            ("data_scheme", "see data:text/html,x", "invalid_url"),
            ("vbscript_scheme", "run vbscript:msgbox", "invalid_url"),
            ("fullwidth_url", "go \uff48\uff54\uff54\uff50\uff1a\uff0f\uff0fevil.com", "invalid_url"),
            ("lt", "foo<bar", "invalid_bracket"),
            ("gt", "link > here", "invalid_bracket"),
            ("zero_width", "foo\u200bbar", "invalid_invisible_char"),
            ("rtl_override", "foo\u202ebar", "invalid_invisible_char"),
        ]
    )
    def test_rejects(self, _name: str, value: str, expected_code: str) -> None:
        with self.assertRaises(serializers.ValidationError) as cm:
            validate_display_name(value)
        detail = cast(list[ErrorDetail], cm.exception.detail)
        assert detail[0].code == expected_code


class TestValidateMessageBody(SimpleTestCase):
    def test_allows_newlines(self) -> None:
        value = "Hey!\nWelcome to the team.\nCheers."
        assert validate_message_body(value) == value

    @parameterized.expand(
        [
            ("bare_domain_filename", "check the foo.py file"),
            ("bare_domain_doc", "see README.md"),
            ("acronym", "contact us at St. John's"),
        ]
    )
    def test_allows_bare_domains(self, _name: str, value: str) -> None:
        assert validate_message_body(value) == value

    @parameterized.expand(
        [
            ("url", "Check https://evil.com", "invalid_url"),
            ("www", "Visit www.scam.io", "invalid_url"),
            ("javascript_scheme", "click javascript:alert(1)", "invalid_url"),
            ("data_scheme", "see data:text/html,x", "invalid_url"),
            ("fullwidth_url", "go \uff48\uff54\uff54\uff50\uff1a\uff0f\uff0fevil.com", "invalid_url"),
            ("bracket", "hello <there>", "invalid_bracket"),
            ("invisible", "foo\u200bbar", "invalid_invisible_char"),
            ("rtl_override", "foo\u202ebar", "invalid_invisible_char"),
            ("non_newline_control", "foo\x01bar", "invalid_control_char"),
            ("carriage_return", "foo\rbar", "invalid_control_char"),
            ("del", "foo\x7fbar", "invalid_control_char"),
            ("line_separator", "foo\u2028bar", "invalid_control_char"),
        ]
    )
    def test_rejects(self, _name: str, value: str, expected_code: str) -> None:
        with self.assertRaises(serializers.ValidationError) as cm:
            validate_message_body(value)
        detail = cast(list[ErrorDetail], cm.exception.detail)
        assert detail[0].code == expected_code

    def test_allows_tab(self) -> None:
        value = "Indented:\n\tline"
        assert validate_message_body(value) == value

    def test_blank_passes_through(self) -> None:
        assert validate_message_body(None) is None
        assert validate_message_body("") == ""
        assert validate_message_body("   ") == "   "
        assert validate_message_body("   \n\t  ") == "   \n\t  "
