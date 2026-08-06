import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from ee.billing.salesforce_enrichment.harmonic_client import AsyncHarmonicClient


def _response(*, json_data=None, raise_status=None, status=200):
    resp = MagicMock()
    resp.status = status
    resp.raise_for_status = MagicMock(side_effect=raise_status)
    resp.json = AsyncMock(return_value=json_data)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _client_with_responses(*responses):
    client = AsyncHarmonicClient.__new__(AsyncHarmonicClient)
    client.api_key = "test-key"
    session = MagicMock()
    session.post = MagicMock(side_effect=list(responses))
    client.session = session
    return client


def _client_with_get_responses(*responses):
    client = AsyncHarmonicClient.__new__(AsyncHarmonicClient)
    client.api_key = "test-key"
    session = MagicMock()
    session.get = MagicMock(side_effect=list(responses))
    client.session = session
    return client


def _not_found():
    return _response(json_data={"data": {"enrichCompanyByIdentifiers": {"companyFound": False}}})


def _found(company):
    return _response(json_data={"data": {"enrichCompanyByIdentifiers": {"companyFound": True, "company": company}}})


def _http_500():
    error = aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=500, message="Server Error")
    return _response(raise_status=error)


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_returns_none_when_not_found():
    # Both domain variations return a clean companyFound=false.
    client = _client_with_responses(_not_found(), _not_found())
    assert await client.enrich_company_by_domain_strict("unknown.example") is None


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_reraises_on_http_error():
    client = _client_with_responses(_http_500(), _http_500())
    with pytest.raises(aiohttp.ClientResponseError):
        await client.enrich_company_by_domain_strict("posthog.com")


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_falls_back_to_second_variation_after_error():
    # First variation errors, second returns a company: the successful variation wins.
    client = _client_with_responses(_http_500(), _found({"name": "PostHog"}))
    result = await client.enrich_company_by_domain_strict("posthog.com")
    assert result == {"name": "PostHog"}


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_get_company_by_urn_returns_parsed_json():
    client = _client_with_get_responses(
        _response(json_data={"name": "Salesforce", "website": {"domain": "salesforce.com"}})
    )
    result = await client.get_company_by_urn("urn:harmonic:company:9801263")
    assert result == {"name": "Salesforce", "website": {"domain": "salesforce.com"}}
    client.session.get.assert_called_once_with(
        "https://api.harmonic.ai/companies/9801263",
        headers={"apikey": "test-key"},
        timeout=aiohttp.ClientTimeout(total=10),
    )


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_get_company_by_urn_returns_none_on_not_found():
    client = _client_with_get_responses(_response(status=404))
    assert await client.get_company_by_urn("urn:harmonic:company:999999999") is None


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_get_company_by_urn_reraises_on_http_error():
    client = _client_with_get_responses(_http_500())
    with pytest.raises(aiohttp.ClientResponseError):
        await client.get_company_by_urn("urn:harmonic:company:9801263")
