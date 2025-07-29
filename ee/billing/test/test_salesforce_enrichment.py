import json
from pathlib import Path
from posthog.test.base import BaseTest
from ee.billing.salesforce_enrichment.enrichment import (
    is_excluded_domain,
    transform_harmonic_data,
)


def load_harmonic_fixture():
    """Load real Harmonic API response fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "harmonic_api_response.json"
    with open(fixture_path) as f:
        data = json.load(f)
    return data["response"]


class TestDomainExclusion(BaseTest):
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
        assert is_excluded_domain("notgmail.com") is False  # Similar but not excluded


class TestHarmonicDataTransformation(BaseTest):
    def test_transform_harmonic_data_with_fixture(self):
        """Test transform_harmonic_data output structure and field mapping with real fixture."""
        harmonic_response = load_harmonic_fixture()
        result = transform_harmonic_data(harmonic_response)

        # Top-level structure
        assert result is not None
        assert "company_info" in result
        assert "funding" in result
        assert "metrics" in result

        # Company info fields
        company_info = result["company_info"]
        assert company_info["name"] == "Example Corp"
        assert company_info["type"] == "STARTUP"
        assert company_info["website"] == "https://example.com"
        assert company_info["founding_date"] == "1983-01-01T00:00:00Z"
        assert company_info["description"] is not None

        # Funding fields
        funding = result["funding"]
        assert funding["fundingTotal"] == 900000000
        assert funding["fundingStage"] == "EXITED"
        assert funding["lastFundingTotal"] == 500000000
        assert funding["lastFundingAt"] == "2025-02-25T00:00:00Z"

        # Metrics
        metrics = result["metrics"]
        assert isinstance(metrics, dict)

        # Verify specific metric values from fixture
        assert metrics["webTraffic"]["current_value"] == 551400
        assert metrics["webTraffic"]["historical"]["90d"]["value"] == 590100
        assert metrics["webTraffic"]["historical"]["180d"]["value"] == 711800

        assert metrics["linkedinFollowerCount"]["current_value"] == 106393
        assert metrics["linkedinFollowerCount"]["historical"]["90d"]["value"] == 99011
        assert metrics["linkedinFollowerCount"]["historical"]["180d"]["value"] == 93634

        assert metrics["twitterFollowerCount"]["current_value"] == 1860
        # twitterFollowerCount has no historical data within 16-day tolerance
        assert metrics["twitterFollowerCount"]["historical"] == {}

        assert metrics["headcount"]["current_value"] == 5015
        assert metrics["headcount"]["historical"]["90d"]["value"] == 4893
        assert metrics["headcount"]["historical"]["180d"]["value"] == 4864

        assert metrics["headcountEngineering"]["current_value"] == 916
        assert metrics["headcountEngineering"]["historical"]["90d"]["value"] == 880
        assert metrics["headcountEngineering"]["historical"]["180d"]["value"] == 886
