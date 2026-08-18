from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.cdp.email_sender import email_integration_domain, override_off_domain_reason


class TestEmailSender(SimpleTestCase):
    @parameterized.expand(
        [
            ("explicit domain", {"domain": "Posthog.com"}, "posthog.com"),
            ("falls back to email domain", {"email": "hi@Example.COM"}, "example.com"),
            ("prefers domain over email", {"domain": "a.com", "email": "hi@b.com"}, "a.com"),
            ("empty when neither present", {}, ""),
        ]
    )
    def test_email_integration_domain(self, _name: str, config: dict, expected: str) -> None:
        assert email_integration_domain(config) == expected

    def test_on_domain_override_is_honored(self) -> None:
        assert override_off_domain_reason({"domain": "posthog.com"}, "sales@posthog.com") is None

    @parameterized.expand(
        [
            ("off domain", {"domain": "posthog.com"}, "default@example.com"),
            ("subdomain does not match", {"domain": "posthog.com"}, "hi@mail.posthog.com"),
            ("integration has no domain", {}, "hi@posthog.com"),
        ]
    )
    def test_off_domain_override_is_reported(self, _name: str, config: dict, override: str) -> None:
        assert override_off_domain_reason(config, override) is not None

    @parameterized.expand([("no at sign", "notanemail"), ("two addresses", "a@x.com,b@x.com")])
    def test_invalid_override_is_reported(self, _name: str, override: str) -> None:
        reason = override_off_domain_reason({"domain": "x.com"}, override)
        assert reason == "it is not a valid email address"
