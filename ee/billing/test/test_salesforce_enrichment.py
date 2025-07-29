from posthog.test.base import BaseTest
from ee.billing.salesforce_enrichment.enrichment import is_excluded_domain


class TestSalesforceEnrichment(BaseTest):
    def test_is_excluded_domain_handles_none_and_empty(self):
        """Test that None and empty domains are excluded (safe default)."""
        assert is_excluded_domain(None) is True
        assert is_excluded_domain("") is True
        assert is_excluded_domain("   ") is True

    def test_is_excluded_domain_standard_personal_domains(self):
        """Test standard personal email domains are excluded."""
        assert is_excluded_domain("gmail.com") is True
        assert is_excluded_domain("yahoo.com") is True
        assert is_excluded_domain("hotmail.com") is True
        assert is_excluded_domain("outlook.com") is True

    def test_is_excluded_domain_international_domains(self):
        """Test international domains (3+ parts) are excluded."""
        assert is_excluded_domain("yahoo.co.uk") is True
        assert is_excluded_domain("yahoo.com.au") is True
        assert is_excluded_domain("yahoo.co.jp") is True

    def test_is_excluded_domain_subdomains(self):
        """Test that subdomains of personal domains are excluded."""
        assert is_excluded_domain("mail.gmail.com") is True
        assert is_excluded_domain("login.yahoo.com") is True
        assert is_excluded_domain("accounts.yahoo.com") is True

    def test_is_excluded_domain_www_prefix_handling(self):
        """Test that www prefix is stripped correctly."""
        assert is_excluded_domain("www.gmail.com") is True
        assert is_excluded_domain("www.yahoo.co.uk") is True

    def test_is_excluded_domain_case_insensitive(self):
        """Test case insensitive matching."""
        assert is_excluded_domain("GMAIL.COM") is True
        assert is_excluded_domain("Yahoo.Com") is True

    def test_is_excluded_domain_business_domains(self):
        """Test that business domains are not excluded."""
        assert is_excluded_domain("posthog.com") is False
        assert is_excluded_domain("stripe.com") is False
        assert is_excluded_domain("microsoft.com") is False
        assert is_excluded_domain("api.example.com") is False

    def test_is_excluded_domain_edge_cases(self):
        """Test edge cases and malformed domains."""
        assert is_excluded_domain("gmail") is False  # No TLD
        assert is_excluded_domain(".com") is False  # No domain
