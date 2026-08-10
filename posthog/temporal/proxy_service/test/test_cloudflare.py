from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.temporal.proxy_service.cloudflare import (
    CloudflareAPIError,
    CustomHostnameSSLStatus,
    CustomHostnameStatus,
    _parse_hostname,
)

# Transcribed from Cloudflare's Custom Hostname API docs, not from the enums under test:
# https://developers.cloudflare.com/api/resources/custom_hostnames/methods/get/
CLOUDFLARE_SSL_STATUSES = [
    "initializing",
    "pending_validation",
    "deleted",
    "pending_issuance",
    "pending_deployment",
    "pending_deletion",
    "pending_expiration",
    "expired",
    "active",
    "initializing_timed_out",
    "validation_timed_out",
    "issuance_timed_out",
    "deployment_timed_out",
    "deletion_timed_out",
    "pending_cleanup",
    "staging_deployment",
    "staging_active",
    "deactivating",
    "inactive",
    "backup_issued",
    "holding_deployment",
]

CLOUDFLARE_HOSTNAME_STATUSES = [
    "active",
    "pending",
    "active_redeploying",
    "moved",
    "pending_deletion",
    "deleted",
    "pending_blocked",
    "pending_migration",
    "pending_provisioned",
    "test_pending",
    "test_active",
    "test_active_apex",
    "test_blocked",
    "test_failed",
    "provisioned",
    "blocked",
]


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


def _hostname_payload(status="active", ssl_status="active"):
    return {
        "id": "abc123",
        "hostname": "p.example.com",
        "status": status,
        "ssl": {"status": ssl_status, "validation_errors": []},
    }


class TestParseHostnameStatuses(SimpleTestCase):
    @parameterized.expand([(status,) for status in CLOUDFLARE_SSL_STATUSES])
    def test_parses_every_documented_ssl_status(self, ssl_status):
        info = _parse_hostname(_hostname_payload(ssl_status=ssl_status))
        self.assertEqual(info.ssl.status.value, ssl_status)

    @parameterized.expand([(status,) for status in CLOUDFLARE_HOSTNAME_STATUSES])
    def test_parses_every_documented_hostname_status(self, status):
        info = _parse_hostname(_hostname_payload(status=status))
        self.assertEqual(info.status.value, status)

    @parameterized.expand(
        [
            ("ssl", {"ssl_status": "some_future_status"}, "some_future_status"),
            ("hostname", {"status": "some_future_status"}, "some_future_status"),
        ]
    )
    def test_keeps_the_raw_value_of_an_unmodeled_status(self, field, payload_kwargs, expected):
        info = _parse_hostname(_hostname_payload(**payload_kwargs))
        parsed = info.ssl.status if field == "ssl" else info.status
        self.assertEqual(parsed.value, expected)

    def test_an_unmodeled_ssl_status_is_not_active(self):
        info = _parse_hostname(_hostname_payload(ssl_status="some_future_status"))
        self.assertNotEqual(info.ssl.status, CustomHostnameSSLStatus.ACTIVE)

    def test_an_unmodeled_hostname_status_is_not_active(self):
        info = _parse_hostname(_hostname_payload(status="some_future_status"))
        self.assertNotEqual(info.status, CustomHostnameStatus.ACTIVE)
