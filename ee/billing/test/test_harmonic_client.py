import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from parameterized import parameterized

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


def _not_found(urn=None):
    return _response(json_data={"data": {"enrichCompanyByIdentifiers": {"companyFound": False, "enrichmentUrn": urn}}})


def _found(company, urn=None):
    return _response(
        json_data={
            "data": {"enrichCompanyByIdentifiers": {"companyFound": True, "company": company, "enrichmentUrn": urn}}
        }
    )


def _missing_company_found_key():
    return _response(json_data={"data": {"enrichCompanyByIdentifiers": {}}})


def _graphql_errors():
    return _response(json_data={"errors": [{"message": "internal error"}]})


def _http_500():
    error = aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=500, message="Server Error")
    return _response(raise_status=error)


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_returns_none_when_not_found():
    # Both domain variations return a clean companyFound=false.
    client = _client_with_responses(_not_found(), _not_found())
    result = await client.enrich_company_by_domain_strict("unknown.example")
    assert result.company is None


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
    assert result.company == {"name": "PostHog"}


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_clean_not_found_is_authoritative_when_the_other_variation_errored():
    # One variation errored, the other returned a clean companyFound=false: that clean answer
    # is an authoritative not-found. Raising here made a deterministically-failing variation
    # exhaust the caller's retries and leave the org with no archive row at all.
    client = _client_with_responses(_http_500(), _not_found())
    result = await client.enrich_company_by_domain_strict("posthog.com")
    assert result.company is None


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_clean_not_found_first_then_error_is_also_not_found():
    client = _client_with_responses(_not_found(), _http_500())
    result = await client.enrich_company_by_domain_strict("posthog.com")
    assert result.company is None


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_raises_when_companyfound_key_missing_and_sibling_errored():
    client = _client_with_responses(_http_500(), _missing_company_found_key())
    with pytest.raises(aiohttp.ClientResponseError):
        await client.enrich_company_by_domain_strict("posthog.com")


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_graphql_error_with_clean_not_found_sibling_returns_none():
    client = _client_with_responses(_graphql_errors(), _not_found())
    result = await client.enrich_company_by_domain_strict("posthog.com")
    assert result.company is None


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
@patch("ee.billing.salesforce_enrichment.harmonic_client.capture_exception")
async def test_strict_captures_swallowed_error_on_mixed_path(mock_capture_exception):
    client = _client_with_responses(_graphql_errors(), _not_found())
    result = await client.enrich_company_by_domain_strict("posthog.com")
    assert result.company is None
    mock_capture_exception.assert_called_once()


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_not_found_surfaces_the_tracking_urn():
    client = _client_with_responses(
        _not_found(urn="urn:harmonic:enrichment:abc"), _not_found(urn="urn:harmonic:enrichment:abc")
    )
    result = await client.enrich_company_by_domain_strict("unknown.example")
    assert result.company is None
    assert result.enrichment_urn == "urn:harmonic:enrichment:abc"


@parameterized.expand(
    [
        ("no_pending_refresh", None),
        ("pending_refresh", "urn:harmonic:enrichment:refresh"),
    ]
)
@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_found_surfaces_the_refresh_urn(_name, urn):
    client = _client_with_responses(_found({"name": "PostHog"}, urn=urn))
    result = await client.enrich_company_by_domain_strict("posthog.com")
    assert result.company == {"name": "PostHog"}
    assert result.enrichment_urn == urn


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_strict_sends_api_key_as_header_not_in_url_or_params():
    client = _client_with_responses(_found({"name": "PostHog"}))
    await client.enrich_company_by_domain_strict("posthog.com")

    client.session.post.assert_called_once()
    call = client.session.post.call_args
    url = call.args[0]
    params = call.kwargs.get("params")

    assert call.kwargs["headers"]["apikey"] == "test-key"
    assert "test-key" not in url
    assert params is None or "test-key" not in str(params)


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_non_strict_sends_api_key_as_header_not_in_url_or_params():
    client = _client_with_responses(_found({"name": "PostHog"}))
    await client.enrich_company_by_domain("posthog.com")

    call = client.session.post.call_args
    params = call.kwargs.get("params")

    assert call.kwargs["headers"]["apikey"] == "test-key"
    assert "test-key" not in call.args[0]
    assert params is None or "test-key" not in str(params)


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


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_get_enrichment_status_builds_repeated_urns_query_and_maps_by_entity_urn():
    entries = [
        {"entity_urn": "urn:harmonic:enrichment:aaa", "status": "COMPLETE", "enriched_entity_urn": "urn:x:1"},
        {"entity_urn": "urn:harmonic:enrichment:bbb", "status": "QUEUED", "enriched_entity_urn": None},
    ]
    client = _client_with_get_responses(_response(json_data=entries))
    result = await client.get_enrichment_status(["urn:harmonic:enrichment:aaa", "urn:harmonic:enrichment:bbb"])

    assert result == {
        "urn:harmonic:enrichment:aaa": entries[0],
        "urn:harmonic:enrichment:bbb": entries[1],
    }
    client.session.get.assert_called_once()
    call = client.session.get.call_args
    assert call.args[0] == "https://api.harmonic.ai/enrichment_status"
    assert call.kwargs["params"] == [
        ("urns", "urn:harmonic:enrichment:aaa"),
        ("urns", "urn:harmonic:enrichment:bbb"),
    ]
    assert call.kwargs["headers"]["apikey"] == "test-key"
    assert "test-key" not in call.args[0]


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_get_enrichment_status_raises_on_non_list_body():
    client = _client_with_get_responses(_response(json_data={"error": "not a list"}))
    with pytest.raises(ValueError):
        await client.get_enrichment_status(["urn:harmonic:enrichment:aaa"])


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new=AsyncMock())
async def test_get_enrichment_status_reraises_on_http_error():
    client = _client_with_get_responses(_http_500())
    with pytest.raises(aiohttp.ClientResponseError):
        await client.get_enrichment_status(["urn:harmonic:enrichment:aaa"])
