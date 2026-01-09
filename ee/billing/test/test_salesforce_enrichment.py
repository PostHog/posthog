import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from ee.billing.salesforce_enrichment.enrichment import (
    _extract_domain,
    enrich_accounts_async,
    get_salesforce_accounts_by_domain,
    is_excluded_domain,
    prepare_salesforce_update_data,
    transform_harmonic_data,
)


@contextmanager
def mock_harmonic_client():
    """Context manager providing a mocked AsyncHarmonicClient."""
    with patch("ee.billing.salesforce_enrichment.enrichment.AsyncHarmonicClient") as mock_class:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_class.return_value = mock_client
        yield mock_client


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


class TestExtractDomain(BaseTest):
    """Unit tests for _extract_domain helper function."""

    @parameterized.expand(
        [
            # (input, expected_output, description)
            ("example.com", "example.com", "bare domain"),
            ("https://example.com", "example.com", "domain with https"),
            ("http://example.com", "example.com", "domain with http"),
            ("www.example.com", "example.com", "domain with www prefix"),
            ("https://www.example.com", "example.com", "full URL with www"),
            ("EXAMPLE.COM", "example.com", "uppercase domain"),
            ("  example.com  ", "example.com", "domain with whitespace"),
            ("https://subdomain.example.com", "subdomain.example.com", "subdomain"),
            ("https://example.com/path", "example.com", "domain with path"),
            ("https://example.com:8080", "example.com", "domain with port"),
            ("https://example.com/path?query=1", "example.com", "domain with path and query"),
            ("https://www.EXAMPLE.com/Path?query=1", "example.com", "complex URL"),
            ("", None, "empty string"),
            (None, None, "None input"),
            ("   ", None, "whitespace only"),
            ("WWW.EXAMPLE.COM", "example.com", "uppercase with www"),
            ("https://www.example.com:443/path#fragment", "example.com", "full URL with all parts"),
        ]
    )
    def test_extract_domain(self, input_url, expected, description):
        result = _extract_domain(input_url)
        assert result == expected, f"Failed for: {description}"


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

        # Tags
        tags = result["tags"]
        assert isinstance(tags, list)
        assert len(tags) == 3
        assert tags[0]["displayValue"] == "Enterprise Software"
        assert tags[0]["isPrimaryTag"] is True

        tags_v2 = result["tagsV2"]
        assert isinstance(tags_v2, list)
        assert len(tags_v2) == 2

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
        assert salesforce_data["harmonic_industry__c"] == "Enterprise Software"
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

    @freeze_time("2025-07-29T12:00:00Z")
    def test_transform_harmonic_data_missing_tags(self):
        """Test transform_harmonic_data handles missing tags."""
        harmonic_data = load_harmonic_fixture()
        del harmonic_data["tags"]
        del harmonic_data["tagsV2"]

        result = transform_harmonic_data(harmonic_data)

        assert result is not None
        assert result["tags"] == []
        assert result["tagsV2"] == []

    @freeze_time("2025-07-29T12:00:00Z")
    def test_prepare_salesforce_update_no_primary_tag_uses_first(self):
        """Test Salesforce update falls back to first tag when there's no primary tag."""
        harmonic_data = load_harmonic_fixture()
        # Remove isPrimaryTag from all tags
        for tag in harmonic_data.get("tags", []):
            tag["isPrimaryTag"] = False

        transformed_data = transform_harmonic_data(harmonic_data)
        salesforce_data = prepare_salesforce_update_data("001TEST", transformed_data)

        # Should use first tag as fallback
        assert salesforce_data["harmonic_industry__c"] == "Enterprise Software"

    @freeze_time("2025-07-29T12:00:00Z")
    def test_prepare_salesforce_update_empty_tags(self):
        """Test Salesforce update when tags array is empty."""
        harmonic_data = load_harmonic_fixture()
        harmonic_data["tags"] = []

        transformed_data = transform_harmonic_data(harmonic_data)
        salesforce_data = prepare_salesforce_update_data("001TEST", transformed_data)

        # harmonic_industry__c should not be in the data (filtered out as None)
        assert "harmonic_industry__c" not in salesforce_data

    @freeze_time("2025-07-29T12:00:00Z")
    def test_prepare_salesforce_update_with_primary_tag(self):
        """Test Salesforce update correctly extracts primary tag."""
        harmonic_data = load_harmonic_fixture()
        transformed_data = transform_harmonic_data(harmonic_data)
        salesforce_data = prepare_salesforce_update_data("001TEST", transformed_data)

        # Primary tag should be extracted
        assert salesforce_data["harmonic_industry__c"] == "Enterprise Software"


class TestSalesforceAccountQuery(BaseTest):
    def test_get_salesforce_accounts_by_domain_escapes_quotes(self):
        """Test that single quotes in domain are properly escaped to prevent SOQL injection."""
        malicious_domain = "test'OR'1'='1"

        mock_sf_client = patch("ee.billing.salesforce_enrichment.enrichment.get_salesforce_client")
        with mock_sf_client as mock_get_sf:
            mock_sf = mock_get_sf.return_value
            mock_sf.query_all.return_value = {"records": []}

            get_salesforce_accounts_by_domain(malicious_domain)

            # Verify query_all was called
            assert mock_sf.query_all.called

            # Get the actual query that was executed
            actual_query = mock_sf.query_all.call_args[0][0]

            # format_soql uses backslash escaping for single quotes
            # Note: domain is lowercased during normalization
            assert "test\\'or\\'1\\'=\\'1" in actual_query
            # Should NOT contain unescaped single quotes that would break query
            assert "test'or'1'='1" not in actual_query.replace("\\'", "")

    def test_get_salesforce_accounts_by_domain_normalizes_domain(self):
        """Test that domain is properly normalized before querying."""
        mock_sf_client = patch("ee.billing.salesforce_enrichment.enrichment.get_salesforce_client")
        with mock_sf_client as mock_get_sf:
            mock_sf = mock_get_sf.return_value
            mock_sf.query_all.return_value = {"records": []}

            # Test with URL instead of plain domain
            get_salesforce_accounts_by_domain("https://www.example.com/path")

            # Should query with normalized domain (exact match or subdomain match)
            actual_query = mock_sf.query_all.call_args[0][0]
            # Verify SOQL query contains expected domain patterns (not URL sanitization)
            # lgtm[py/incomplete-url-substring-sanitization]
            assert "example.com" in actual_query
            assert ".example.com" in actual_query  # subdomain pattern
            assert "www." not in actual_query
            assert "https://" not in actual_query

    def test_get_salesforce_accounts_by_domain_returns_empty_for_invalid(self):
        """Test that invalid domains return empty list."""
        result = get_salesforce_accounts_by_domain("")
        assert result == []

    def test_get_salesforce_accounts_by_domain_returns_empty_for_whitespace(self):
        """Test that whitespace-only domains return empty list."""
        result = get_salesforce_accounts_by_domain("   ")
        assert result == []

    def test_get_salesforce_accounts_by_domain_precise_matching(self):
        """Test that domain matching is precise and doesn't match unintended domains."""
        mock_sf_client = patch("ee.billing.salesforce_enrichment.enrichment.get_salesforce_client")
        with mock_sf_client as mock_get_sf:
            mock_sf = mock_get_sf.return_value
            # Simulate SF returning multiple accounts with similar domains
            mock_sf.query_all.return_value = {
                "records": [
                    {"Id": "001", "Name": "Exact Match", "Domain__c": "example.com"},
                    {"Id": "002", "Name": "Subdomain Match", "Domain__c": "www.example.com"},
                ]
            }

            get_salesforce_accounts_by_domain("example.com")

            # Verify query_all was called
            assert mock_sf.query_all.called

            # Get the actual query that was executed
            actual_query = mock_sf.query_all.call_args[0][0]

            # Verify query uses exact match OR subdomain match pattern
            # Should match: example.com (exact) or *.example.com (subdomain)
            # Should NOT match: tryexample.com or example.com.evil.com
            assert "Domain__c = " in actual_query  # exact match clause
            assert "Domain__c LIKE " in actual_query  # subdomain match clause
            assert ".example.com" in actual_query  # subdomain pattern with dot prefix

            # Verify it doesn't use the old %domain% pattern that would match unintended domains
            assert "LIKE '%example.com%'" not in actual_query


class TestSpecificDomainEnrichment(BaseTest):
    @pytest.mark.asyncio
    @freeze_time("2025-07-29T12:00:00Z")
    async def test_specific_domain_enrichment_success(self):
        """Test enriching a specific domain returns Harmonic data and updates Salesforce."""
        harmonic_response = load_harmonic_fixture()

        # Mock Salesforce accounts
        mock_accounts = [
            {"Id": "001EXAMPLE1", "Name": "Test Company 1", "Domain__c": "example.com"},
            {"Id": "001EXAMPLE2", "Name": "Test Company 2", "Domain__c": "example.com"},
        ]

        with mock_harmonic_client() as mock_client:
            mock_client.enrich_companies_batch = AsyncMock(return_value=[harmonic_response])

            with patch(
                "ee.billing.salesforce_enrichment.enrichment.get_salesforce_accounts_by_domain",
                return_value=mock_accounts,
            ):
                with patch(
                    "ee.billing.salesforce_enrichment.enrichment.bulk_update_salesforce_accounts"
                ) as mock_bulk_update:
                    result = await enrich_accounts_async(specific_domain="example.com")

                    # Check summary
                    assert result["summary"]["harmonic_data_found"] is True
                    assert result["summary"]["salesforce_update_succeeded"] is True
                    assert result["summary"]["salesforce_accounts_count"] == 2
                    assert result["summary"]["accounts_updated"] == 2

                    # Check counts
                    assert result["records_processed"] == 2
                    assert result["records_enriched"] == 1
                    assert result["records_updated"] == 2

                    # Check data
                    assert result["enriched_data"] is not None
                    assert result["enriched_data"]["company_info"]["name"] == "Example Corp"
                    assert result["raw_harmonic_response"] == harmonic_response

                    # Verify Harmonic called once
                    mock_client.enrich_companies_batch.assert_called_once_with(["example.com"])

                    # Verify Salesforce bulk update called with 2 accounts
                    mock_bulk_update.assert_called_once()
                    update_records = mock_bulk_update.call_args[0][1]
                    assert len(update_records) == 2

    @pytest.mark.asyncio
    @freeze_time("2025-07-29T12:00:00Z")
    async def test_specific_domain_enrichment_with_full_url(self):
        """Test enriching a specific domain from a full URL."""
        harmonic_response = load_harmonic_fixture()

        mock_accounts = [
            {"Id": "001EXAMPLE1", "Name": "Test Company 1", "Domain__c": "example.com"},
        ]

        with mock_harmonic_client() as mock_client:
            mock_client.enrich_companies_batch = AsyncMock(return_value=[harmonic_response])

            with patch(
                "ee.billing.salesforce_enrichment.enrichment.get_salesforce_accounts_by_domain",
                return_value=mock_accounts,
            ):
                with patch("ee.billing.salesforce_enrichment.enrichment.bulk_update_salesforce_accounts"):
                    result = await enrich_accounts_async(specific_domain="https://www.example.com/path")

                    assert result["records_enriched"] == 1
                    assert result["enriched_data"] is not None
                    mock_client.enrich_companies_batch.assert_called_once_with(["example.com"])

    @pytest.mark.asyncio
    async def test_specific_domain_enrichment_excluded_domain(self):
        """Test that personal email domains are excluded."""
        result = await enrich_accounts_async(specific_domain="gmail.com")

        assert result["records_processed"] == 1
        assert result["records_enriched"] == 0
        assert result["summary"]["harmonic_data_found"] is False
        assert result["summary"]["salesforce_update_succeeded"] is False
        assert "excluded" in result["error"]

    @pytest.mark.asyncio
    @freeze_time("2025-07-29T12:00:00Z")
    async def test_specific_domain_enrichment_no_harmonic_data(self):
        """Test handling when Harmonic returns no data for domain."""
        mock_accounts = [
            {"Id": "001EXAMPLE1", "Name": "Test Company 1", "Domain__c": "unknown-domain.xyz"},
        ]

        with mock_harmonic_client() as mock_client:
            mock_client.enrich_companies_batch = AsyncMock(return_value=[None])

            with patch(
                "ee.billing.salesforce_enrichment.enrichment.get_salesforce_accounts_by_domain",
                return_value=mock_accounts,
            ):
                result = await enrich_accounts_async(specific_domain="unknown-domain.xyz")

                assert result["records_processed"] == 1
                assert result["records_enriched"] == 0
                assert result["summary"]["harmonic_data_found"] is False
                assert result["summary"]["salesforce_update_succeeded"] is False
                assert "No Harmonic data found" in result["error"]

    @pytest.mark.asyncio
    @freeze_time("2025-07-29T12:00:00Z")
    async def test_specific_domain_no_salesforce_accounts(self):
        """Test handling when no Salesforce accounts match the domain."""
        with patch("ee.billing.salesforce_enrichment.enrichment.get_salesforce_accounts_by_domain", return_value=[]):
            result = await enrich_accounts_async(specific_domain="nonexistent-domain.com")

            assert result["records_processed"] == 1
            assert result["records_enriched"] == 0
            assert result["summary"]["harmonic_data_found"] is False
            assert result["summary"]["salesforce_update_succeeded"] is False
            assert result["summary"]["salesforce_accounts_count"] == 0
            assert "No Salesforce accounts found" in result["error"]

    @pytest.mark.asyncio
    @freeze_time("2025-07-29T12:00:00Z")
    async def test_specific_domain_calls_salesforce_and_updates(self):
        """Test that specific_domain queries Salesforce and updates matching accounts."""
        harmonic_response = load_harmonic_fixture()
        mock_accounts = [
            {"Id": "001EXAMPLE1", "Name": "Test Company 1", "Domain__c": "example.com"},
        ]

        with mock_harmonic_client() as mock_client:
            mock_client.enrich_companies_batch = AsyncMock(return_value=[harmonic_response])

            with patch(
                "ee.billing.salesforce_enrichment.enrichment.get_salesforce_accounts_by_domain",
                return_value=mock_accounts,
            ) as mock_get_accounts:
                with patch(
                    "ee.billing.salesforce_enrichment.enrichment.bulk_update_salesforce_accounts"
                ) as mock_bulk_update:
                    result = await enrich_accounts_async(specific_domain="example.com")

                    # Verify Salesforce was queried
                    mock_get_accounts.assert_called_once_with("example.com")

                    # Verify Salesforce was updated
                    mock_bulk_update.assert_called_once()

                    # Verify result
                    assert result["summary"]["salesforce_update_succeeded"] is True

    @pytest.mark.asyncio
    @freeze_time("2025-07-29T12:00:00Z")
    async def test_specific_domain_multiple_accounts_all_updated(self):
        """Test that when multiple Salesforce accounts match a domain, all are updated."""
        harmonic_response = load_harmonic_fixture()

        # Multiple accounts with same domain (duplicate scenario)
        mock_accounts = [
            {"Id": "001ACCOUNT1", "Name": "Company A", "Domain__c": "example.com"},
            {"Id": "001ACCOUNT2", "Name": "Company B", "Domain__c": "example.com"},
            {"Id": "001ACCOUNT3", "Name": "Company C", "Domain__c": "example.com"},
        ]

        with mock_harmonic_client() as mock_client:
            mock_client.enrich_companies_batch = AsyncMock(return_value=[harmonic_response])

            with patch(
                "ee.billing.salesforce_enrichment.enrichment.get_salesforce_accounts_by_domain",
                return_value=mock_accounts,
            ):
                with patch(
                    "ee.billing.salesforce_enrichment.enrichment.bulk_update_salesforce_accounts"
                ) as mock_bulk_update:
                    result = await enrich_accounts_async(specific_domain="example.com")

                    # Check summary shows all accounts
                    assert result["summary"]["harmonic_data_found"] is True
                    assert result["summary"]["salesforce_update_succeeded"] is True
                    assert result["summary"]["salesforce_accounts_count"] == 3
                    assert result["summary"]["accounts_updated"] == 3
                    assert len(result["summary"]["salesforce_accounts"]) == 3

                    # Check counts reflect all accounts processed
                    assert result["records_processed"] == 3
                    assert result["records_enriched"] == 1  # Harmonic called once
                    assert result["records_updated"] == 3  # All 3 accounts updated

                    # Verify Harmonic called only once (efficient)
                    mock_client.enrich_companies_batch.assert_called_once_with(["example.com"])

                    # Verify all 3 accounts passed to bulk update
                    mock_bulk_update.assert_called_once()
                    update_records = mock_bulk_update.call_args[0][1]
                    assert len(update_records) == 3

                    # Verify each account ID is in the update batch
                    updated_ids = {record["Id"] for record in update_records}
                    assert updated_ids == {"001ACCOUNT1", "001ACCOUNT2", "001ACCOUNT3"}

    @pytest.mark.asyncio
    @freeze_time("2025-07-29T12:00:00Z")
    async def test_specific_domain_enrichment_returns_updated_account_data(self):
        """Test that updated_salesforce_accounts contains the refreshed SF data after update."""
        harmonic_response = load_harmonic_fixture()

        mock_accounts = [
            {"Id": "001EXAMPLE1", "Name": "Test Company", "Domain__c": "example.com"},
        ]

        # Mock the updated account data returned by the SOQL query
        mock_updated_account = {
            "Id": "001EXAMPLE1",
            "Name": "Test Company",
            "Domain__c": "example.com",
            "harmonic_company_name__c": "Example Corp",
            "harmonic_company_type__c": "STARTUP",
            "harmonic_headcount__c": 5015,
            "harmonic_industry__c": "Technology",
            "harmonic_description__c": "A technology company",
            "harmonic_city__c": "San Francisco",
            "harmonic_state__c": "CA",
            "harmonic_country__c": "USA",
            "harmonic_founding_date__c": "1983-01-01",
            "harmonic_funding_total__c": 900000000,
            "harmonic_funding_rounds__c": 5,
            "harmonic_last_funding_date__c": "2025-02-25",
            "harmonic_last_funding_type__c": "Series E",
            "harmonic_last_funding_total__c": 500000000,
            "harmonic_funding_stage__c": "EXITED",
        }

        with mock_harmonic_client() as mock_client:
            mock_client.enrich_companies_batch = AsyncMock(return_value=[harmonic_response])

            with patch(
                "ee.billing.salesforce_enrichment.enrichment.get_salesforce_accounts_by_domain",
                return_value=mock_accounts,
            ):
                with patch("ee.billing.salesforce_enrichment.enrichment.bulk_update_salesforce_accounts"):
                    with patch("ee.billing.salesforce_enrichment.enrichment.get_salesforce_client") as mock_get_sf:
                        mock_sf = mock_get_sf.return_value
                        # Mock the single SOQL query that fetches updated accounts
                        mock_sf.query_all.return_value = {"records": [mock_updated_account]}

                        result = await enrich_accounts_async(specific_domain="example.com")

                        # Verify updated_salesforce_accounts is populated
                        assert "updated_salesforce_accounts" in result
                        assert len(result["updated_salesforce_accounts"]) == 1

                        updated_account = result["updated_salesforce_accounts"][0]
                        assert updated_account["Id"] == "001EXAMPLE1"
                        assert updated_account["Name"] == "Test Company"
                        assert updated_account["harmonic_company_name__c"] == "Example Corp"
                        assert updated_account["harmonic_company_type__c"] == "STARTUP"
                        assert updated_account["harmonic_headcount__c"] == 5015
                        assert updated_account["harmonic_funding_stage__c"] == "EXITED"

                        # Verify query_all was called to fetch the updated data
                        assert mock_sf.query_all.called
