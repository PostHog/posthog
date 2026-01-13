import json
from pathlib import Path

from freezegun import freeze_time
from posthog.test.base import BaseTest

from ee.billing.salesforce_enrichment.enrichment import (
    is_excluded_domain,
    prepare_salesforce_update_data,
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
    @freeze_time("2025-07-29T12:00:00Z")
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

    @freeze_time("2025-07-29T12:00:00Z")
    def test_prepare_salesforce_update_data_with_fixture(self):
        """Test complete pipeline: fixture → transform → Salesforce field mapping."""
        # Load and transform fixture data
        harmonic_response = load_harmonic_fixture()
        transformed_data = transform_harmonic_data(harmonic_response)
        account_id = "001EXAMPLE123"

        # Prepare Salesforce update data
        salesforce_data = prepare_salesforce_update_data(account_id, transformed_data)

        # Basic structure validation
        assert salesforce_data is not None
        assert salesforce_data["Id"] == account_id

        # Company info fields
        assert salesforce_data["harmonic_company_name__c"] == "Example Corp"
        assert salesforce_data["harmonic_company_type__c"] == "STARTUP"
        assert "harmonic_last_update__c" in salesforce_data
        assert salesforce_data["Founded_year__c"] == 1983

        # Funding fields
        assert salesforce_data["Total_Funding__c"] == 900000000
        assert salesforce_data["harmonic_funding_stage__c"] == "EXITED"
        assert salesforce_data["harmonic_last_funding__c"] == 500000000
        assert salesforce_data["Last_Funding_Date__c"] == "2025-02-25T00:00:00Z"

        # Current metrics
        assert salesforce_data["harmonic_headcount__c"] == 5015
        assert salesforce_data["harmonic_headcountEngineering__c"] == 916
        assert salesforce_data["harmonic_linkedinFollowerCount__c"] == 106393
        assert salesforce_data["harmonic_twitterFollowerCount__c"] == 1860
        assert salesforce_data["harmonic_web_traffic__c"] == 551400

        # Historical metrics (90d)
        assert salesforce_data["harmonic_headcount_90d__c"] == 4893
        assert salesforce_data["harmonic_headcountEngineering_90d__c"] == 880
        assert salesforce_data["harmonic_linkedinFollowerCount_90d__c"] == 99011
        assert salesforce_data["harmonic_web_traffic_90d__c"] == 590100

        # Historical metrics (180d)
        assert salesforce_data["harmonic_headcount_180d__c"] == 4864
        assert salesforce_data["harmonic_headcountEngineering_180d__c"] == 886
        assert salesforce_data["harmonic_linkedinFollowerCount_180d__c"] == 93634
        assert salesforce_data["harmonic_web_traffic_180d__c"] == 711800

        # twitterFollowerCount historical fields should be filtered out (no data within tolerance)
        assert "harmonic_twitterFollowerCount_90d__c" not in salesforce_data
        assert "harmonic_twitterFollowerCount_180d__c" not in salesforce_data

        # Verify no None values remain
        for key, value in salesforce_data.items():
            assert value is not None, f"Field {key} should not be None"

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_missing_funding(self):
        """Test transform_harmonic_data handles missing funding section."""
        harmonic_data = load_harmonic_fixture()
        del harmonic_data["funding"]

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        assert result["funding"] == {}
        assert result["company_info"]["name"] == "Example Corp"  # Other data preserved

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_missing_company_fields(self):
        """Test transform_harmonic_data handles missing company info fields."""
        harmonic_data = load_harmonic_fixture()
        del harmonic_data["name"]
        del harmonic_data["companyType"]
        del harmonic_data["description"]

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        assert result["company_info"]["name"] is None
        assert result["company_info"]["type"] is None
        assert result["company_info"]["description"] is None
        # Other fields should still work
        assert result["company_info"]["website"] == "https://example.com"

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_malformed_website(self):
        """Test transform_harmonic_data handles malformed website data."""
        harmonic_data = load_harmonic_fixture()
        harmonic_data["website"] = "not-a-dict"  # Should be dict, now string

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        assert result["company_info"]["website"] is None  # Safely handles type mismatch

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_malformed_founding_date(self):
        """Test transform_harmonic_data handles malformed founding date."""
        harmonic_data = load_harmonic_fixture()
        harmonic_data["foundingDate"] = "1983-01-01"  # Should be dict, now string

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        assert result["company_info"]["founding_date"] is None  # Safely handles type mismatch

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_missing_traction_metrics(self):
        """Test transform_harmonic_data handles missing tractionMetrics."""
        harmonic_data = load_harmonic_fixture()
        del harmonic_data["tractionMetrics"]

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        assert result["metrics"] == {}
        # Other sections should still work
        assert result["company_info"]["name"] == "Example Corp"

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_metric_missing_latest_value(self):
        """Test transform_harmonic_data handles metrics without latestMetricValue."""
        harmonic_data = load_harmonic_fixture()
        # Remove latestMetricValue from headcount metric
        del harmonic_data["tractionMetrics"]["headcount"]["latestMetricValue"]

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        # headcount should be excluded from metrics
        assert "headcount" not in result["metrics"]
        # Other metrics should still be present
        assert "webTraffic" in result["metrics"]

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_metric_with_null_latest_value(self):
        """Test transform_harmonic_data handles metrics with null latestMetricValue."""
        harmonic_data = load_harmonic_fixture()
        harmonic_data["tractionMetrics"]["headcount"]["latestMetricValue"] = None

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        # headcount should be excluded from metrics
        assert "headcount" not in result["metrics"]
        # Other metrics should still be present
        assert "webTraffic" in result["metrics"]

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_empty_historical_metrics(self):
        """Test transform_harmonic_data handles empty historical data."""
        harmonic_data = load_harmonic_fixture()
        harmonic_data["tractionMetrics"]["headcount"]["metrics"] = []

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        assert "headcount" in result["metrics"]
        assert result["metrics"]["headcount"]["current_value"] == 5015
        assert result["metrics"]["headcount"]["historical"] == {}
