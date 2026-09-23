from parameterized import parameterized

from products.customer_analytics.backend.domain import parse_company_domain
from products.customer_analytics.backend.logic.account_logo import resolve_logo_domain


class TestParseCompanyDomain:
    @parameterized.expand(
        [
            ("bare", "posthog.com", "posthog.com"),
            ("uppercase", "PostHog.COM", "posthog.com"),
            ("surrounding whitespace", "  posthog.com  ", "posthog.com"),
            ("email suffix", "@posthog.com", "posthog.com"),
            ("www prefix", "www.posthog.com", "posthog.com"),
            ("full url", "https://www.posthog.com/pricing?ref=x", "posthog.com"),
            ("scheme relative url", "//posthog.com", "posthog.com"),
            ("host and port", "posthog.com:8000", "posthog.com"),
            ("fully qualified trailing dot", "posthog.com.", "posthog.com"),
            ("subdomain kept", "eu.posthog.com", "eu.posthog.com"),
        ]
    )
    def test_reduces_stored_value_to_bare_hostname(self, _name: str, raw: str, expected: str) -> None:
        assert parse_company_domain(raw) == expected

    @parameterized.expand(
        [
            ("none", None),
            ("empty", ""),
            ("whitespace only", "   "),
            ("no dot", "posthog"),
            ("uuid group key", "0192d900-d620-0000-46a9-f9a712425410"),
            ("free text", "Acme Corporation"),
            ("mailbox provider", "gmail.com"),
            ("mailbox provider as email suffix", "@outlook.com"),
            ("unbracketed ipv6", "//[::1"),
            ("label over 63 characters", f"{'a' * 64}.com"),
        ]
    )
    def test_returns_none_for_values_that_are_not_a_company_hostname(self, _name: str, raw: str | None) -> None:
        assert parse_company_domain(raw) is None


class TestResolveLogoDomain:
    def test_prefers_the_normalized_website_domain(self) -> None:
        assert resolve_logo_domain(website_domain="acme.example", email_domains=["mail.example"]) == "acme.example"

    def test_falls_back_through_email_domains_that_do_not_resolve(self) -> None:
        assert resolve_logo_domain(website_domain=None, email_domains=["gmail.com", "acme.example"]) == "acme.example"

    def test_returns_none_when_no_source_resolves(self) -> None:
        assert resolve_logo_domain(website_domain=None, email_domains=[]) is None
