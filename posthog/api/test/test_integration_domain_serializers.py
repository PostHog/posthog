from typing import Any

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.api.integration_domain_serializers import (
    DomainConnectApplyUrlRequestSerializer,
    NativeEmailIntegrationSerializer,
)


class TestDomainConnectApplyUrlRequestSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_context", {"integration_id": 1}, "context must be 'email' or 'proxy'"),
            ("unknown_context", {"context": "sms", "integration_id": 1}, "context must be 'email' or 'proxy'"),
            ("email_without_integration", {"context": "email"}, "integration_id is required for email context"),
            ("proxy_without_record", {"context": "proxy"}, "proxy_record_id is required for proxy context"),
            (
                "unknown_provider_endpoint",
                {"context": "email", "integration_id": 1, "provider_endpoint": "dns.example.com"},
                "Unsupported provider endpoint",
            ),
            ("email_with_integration", {"context": "email", "integration_id": 1}, None),
            ("proxy_with_malformed_record", {"context": "proxy", "proxy_record_id": "a1b2"}, "Must be a valid UUID."),
            (
                "proxy_with_record",
                {"context": "proxy", "proxy_record_id": "6f1c1a52-3b7e-4c1e-9d0a-2f4b8e6c9a10"},
                None,
            ),
            ("null_optionals", {"context": "email", "integration_id": 1, "provider_endpoint": None}, None),
        ]
    )
    def test_validation(self, _name: str, data: dict[str, Any], expected_error: str | None) -> None:
        serializer = DomainConnectApplyUrlRequestSerializer(data=data)

        assert serializer.is_valid() is (expected_error is None)
        if expected_error:
            assert expected_error in str(serializer.errors)


class TestNativeEmailIntegrationSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("ses_in_production", "ses", False, True),
            ("maildev_in_production", "maildev", False, False),
            ("maildev_in_development", "maildev", True, True),
        ]
    )
    def test_provider(self, _name: str, provider: str, debug: bool, expected_valid: bool) -> None:
        with override_settings(DEBUG=debug):
            serializer = NativeEmailIntegrationSerializer(
                data={"email": "hello@mail.example.com", "name": "Acme", "provider": provider}
            )

            assert serializer.is_valid() is expected_valid
