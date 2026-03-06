from django.test import TestCase

from parameterized import parameterized

from posthog.temporal.proxy_service.cloudflare import CloudflareAPIError


class TestCloudflareAPIErrorIsRateLimited(TestCase):
    @parameterized.expand(
        [
            ("error_code_10000", "Rate limited", [{"code": 10000}], True),
            ("rate_limit_in_message", "Rate limited. Please wait", [], True),
            ("rate_limit_case_insensitive", "RATE LIMIT exceeded", [], True),
            ("unrelated_error_code", "Some API error", [{"code": 1234}], False),
            ("empty_errors_no_rate_limit", "Cloudflare API error", [], False),
        ]
    )
    def test_is_rate_limited(self, _name, message, errors, expected):
        error = CloudflareAPIError(message, errors=errors)
        self.assertEqual(error.is_rate_limited(), expected)
