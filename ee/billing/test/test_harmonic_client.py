import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from parameterized import parameterized

from posthog.egress.harmonic.transport import HarmonicEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority

from ee.billing.salesforce_enrichment.harmonic_client import AsyncHarmonicClient

HARMONIC_REQUEST = "ee.billing.salesforce_enrichment.harmonic_client.harmonic_request"
PACE_SECONDS_HARMONIC = "ee.billing.salesforce_enrichment.harmonic_client.pace_seconds_harmonic"


def _response(*, json_data=None, raise_status=None, status=200):
    resp = MagicMock()
    resp.status = status
    resp.raise_for_status = MagicMock(side_effect=raise_status)
    resp.json = AsyncMock(return_value=json_data)
    return resp


def _client(*, priority=Priority.NORMAL):
    client = AsyncHarmonicClient.__new__(AsyncHarmonicClient)
    client.api_key = "test-key"
    client.priority = priority
    client.source = "test"
    client.session = MagicMock()
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
async def test_strict_returns_none_when_not_found():
    # Both domain variations return a clean companyFound=false.
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_not_found(), _not_found()])):
        result = await _client().enrich_company_by_domain_strict("unknown.example")
    assert result.company is None


@pytest.mark.asyncio
async def test_strict_reraises_on_http_error():
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_http_500(), _http_500()])):
        with pytest.raises(aiohttp.ClientResponseError):
            await _client().enrich_company_by_domain_strict("posthog.com")


@pytest.mark.asyncio
async def test_strict_falls_back_to_second_variation_after_error():
    # First variation errors, second returns a company: the successful variation wins.
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_http_500(), _found({"name": "PostHog"})])):
        result = await _client().enrich_company_by_domain_strict("posthog.com")
    assert result.company == {"name": "PostHog"}


@pytest.mark.asyncio
async def test_strict_clean_not_found_is_authoritative_when_the_other_variation_errored():
    # One variation errored, the other returned a clean companyFound=false: that clean answer
    # is an authoritative not-found. Raising here made a deterministically-failing variation
    # exhaust the caller's retries and leave the org with no archive row at all.
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_http_500(), _not_found()])):
        result = await _client().enrich_company_by_domain_strict("posthog.com")
    assert result.company is None


@pytest.mark.asyncio
async def test_strict_clean_not_found_first_then_error_is_also_not_found():
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_not_found(), _http_500()])):
        result = await _client().enrich_company_by_domain_strict("posthog.com")
    assert result.company is None


@pytest.mark.asyncio
async def test_strict_raises_when_companyfound_key_missing_and_sibling_errored():
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_http_500(), _missing_company_found_key()])):
        with pytest.raises(aiohttp.ClientResponseError):
            await _client().enrich_company_by_domain_strict("posthog.com")


@pytest.mark.asyncio
async def test_strict_never_swallows_a_shed_variation_into_a_not_found_clean_first():
    # A sibling's clean not-found is authoritative for a genuine network error (see the test
    # above), but not for a shed: a shed means Harmonic was never asked, so the sibling's answer
    # says nothing about it. Swallowing this would write a false not-found the re-enrichment
    # sweep would not revisit for up to 90 days, purely because our own budget was tight.
    side_effect = [_not_found(), HarmonicEgressBudgetExhausted("degrading")]
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=side_effect)):
        with pytest.raises(HarmonicEgressBudgetExhausted):
            await _client(priority=Priority.BATCH).enrich_company_by_domain_strict("posthog.com")


@pytest.mark.asyncio
async def test_strict_never_swallows_a_shed_variation_into_a_not_found_shed_first():
    side_effect = [HarmonicEgressBudgetExhausted("degrading"), _not_found()]
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=side_effect)):
        with pytest.raises(HarmonicEgressBudgetExhausted):
            await _client(priority=Priority.BATCH).enrich_company_by_domain_strict("posthog.com")


@pytest.mark.asyncio
async def test_strict_graphql_error_with_clean_not_found_sibling_returns_none():
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_graphql_errors(), _not_found()])):
        result = await _client().enrich_company_by_domain_strict("posthog.com")
    assert result.company is None


@pytest.mark.asyncio
@patch("ee.billing.salesforce_enrichment.harmonic_client.capture_exception")
async def test_strict_captures_swallowed_error_on_mixed_path(mock_capture_exception):
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_graphql_errors(), _not_found()])):
        result = await _client().enrich_company_by_domain_strict("posthog.com")
    assert result.company is None
    mock_capture_exception.assert_called_once()


@pytest.mark.asyncio
async def test_strict_not_found_surfaces_the_tracking_urn():
    responses = [_not_found(urn="urn:harmonic:enrichment:abc"), _not_found(urn="urn:harmonic:enrichment:abc")]
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=responses)):
        result = await _client().enrich_company_by_domain_strict("unknown.example")
    assert result.company is None
    assert result.enrichment_urn == "urn:harmonic:enrichment:abc"


@parameterized.expand(
    [
        ("no_pending_refresh", None),
        ("pending_refresh", "urn:harmonic:enrichment:refresh"),
    ]
)
@pytest.mark.asyncio
async def test_strict_found_surfaces_the_refresh_urn(_name, urn):
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=[_found({"name": "PostHog"}, urn=urn)])):
        result = await _client().enrich_company_by_domain_strict("posthog.com")
    assert result.company == {"name": "PostHog"}
    assert result.enrichment_urn == urn


@pytest.mark.asyncio
async def test_strict_sends_api_key_as_header_not_in_url_or_params_and_uses_client_priority_and_source():
    client = _client(priority=Priority.BATCH)
    client.source = "billing_bulk"
    mock_request = AsyncMock(side_effect=[_found({"name": "PostHog"})])
    with patch(HARMONIC_REQUEST, new=mock_request):
        await client.enrich_company_by_domain_strict("posthog.com")

    mock_request.assert_called_once()
    call = mock_request.call_args
    assert call.args[0] is client.session
    assert call.args[1] == "POST"
    url = call.args[2]

    assert call.kwargs["headers"]["apikey"] == "test-key"
    assert "test-key" not in url
    assert call.kwargs.get("params") is None
    assert call.kwargs["priority"] is Priority.BATCH
    assert call.kwargs["source"] == "billing_bulk"


@pytest.mark.asyncio
async def test_non_strict_sends_api_key_as_header_not_in_url_or_params():
    mock_request = AsyncMock(side_effect=[_found({"name": "PostHog"})])
    with patch(HARMONIC_REQUEST, new=mock_request):
        await _client().enrich_company_by_domain("posthog.com")

    call = mock_request.call_args
    url = call.args[2]

    assert call.kwargs["headers"]["apikey"] == "test-key"
    assert "test-key" not in url
    assert call.kwargs.get("params") is None


@pytest.mark.asyncio
async def test_non_strict_returns_none_when_every_variation_is_rate_limited():
    # A limiter denial is swallowed by the same per-variation except block as a network error,
    # but must not be reported as one: the limiter already records it as a metric, and paging on
    # our own throttling working as designed would be noise.
    mock_request = AsyncMock(side_effect=HarmonicEgressBudgetExhausted("degrading"))
    with (
        patch(HARMONIC_REQUEST, new=mock_request),
        patch("ee.billing.salesforce_enrichment.harmonic_client.capture_exception") as mock_capture,
    ):
        result = await _client(priority=Priority.BATCH).enrich_company_by_domain("posthog.com")
    assert result is None
    mock_capture.assert_not_called()


@pytest.mark.asyncio
async def test_get_company_by_urn_returns_parsed_json():
    response = _response(json_data={"name": "Salesforce", "website": {"domain": "salesforce.com"}})
    client = _client()
    mock_request = AsyncMock(return_value=response)
    with patch(HARMONIC_REQUEST, new=mock_request):
        result = await client.get_company_by_urn("urn:harmonic:company:9801263")
    assert result == {"name": "Salesforce", "website": {"domain": "salesforce.com"}}
    mock_request.assert_called_once_with(
        client.session,
        "GET",
        "https://api.harmonic.ai/companies/9801263",
        source="test",
        priority=Priority.NORMAL,
        endpoint="/companies/{id}",
        headers={"apikey": "test-key"},
        timeout=aiohttp.ClientTimeout(total=10),
    )


@pytest.mark.asyncio
async def test_get_company_by_urn_returns_none_on_not_found():
    with patch(HARMONIC_REQUEST, new=AsyncMock(return_value=_response(status=404))):
        assert await _client().get_company_by_urn("urn:harmonic:company:999999999") is None


@pytest.mark.asyncio
async def test_get_company_by_urn_reraises_on_http_error():
    with patch(HARMONIC_REQUEST, new=AsyncMock(return_value=_http_500())):
        with pytest.raises(aiohttp.ClientResponseError):
            await _client().get_company_by_urn("urn:harmonic:company:9801263")


@pytest.mark.asyncio
async def test_get_company_by_urn_raises_when_rate_limited():
    # No swallowing here: parent-company resolution is optional, and the caller decides whether
    # to catch this, same as any other operational failure from this method.
    with patch(HARMONIC_REQUEST, new=AsyncMock(side_effect=HarmonicEgressBudgetExhausted("degrading"))):
        with pytest.raises(HarmonicEgressBudgetExhausted):
            await _client(priority=Priority.BATCH).get_company_by_urn("urn:harmonic:company:9801263")


@pytest.mark.asyncio
async def test_get_enrichment_status_builds_repeated_urns_query_and_maps_by_entity_urn():
    entries = [
        {"entity_urn": "urn:harmonic:enrichment:aaa", "status": "COMPLETE", "enriched_entity_urn": "urn:x:1"},
        {"entity_urn": "urn:harmonic:enrichment:bbb", "status": "QUEUED", "enriched_entity_urn": None},
    ]
    client = _client()
    mock_request = AsyncMock(return_value=_response(json_data=entries))
    with patch(HARMONIC_REQUEST, new=mock_request):
        result = await client.get_enrichment_status(["urn:harmonic:enrichment:aaa", "urn:harmonic:enrichment:bbb"])

    assert result == {
        "urn:harmonic:enrichment:aaa": entries[0],
        "urn:harmonic:enrichment:bbb": entries[1],
    }
    mock_request.assert_called_once()
    call = mock_request.call_args
    assert call.args[0] is client.session
    assert call.args[1] == "GET"
    assert call.args[2] == "https://api.harmonic.ai/enrichment_status"
    assert call.kwargs["params"] == [
        ("urns", "urn:harmonic:enrichment:aaa"),
        ("urns", "urn:harmonic:enrichment:bbb"),
    ]
    assert call.kwargs["headers"]["apikey"] == "test-key"
    assert "test-key" not in call.args[2]


@pytest.mark.asyncio
async def test_get_enrichment_status_raises_on_non_list_body():
    with patch(HARMONIC_REQUEST, new=AsyncMock(return_value=_response(json_data={"error": "not a list"}))):
        with pytest.raises(ValueError):
            await _client().get_enrichment_status(["urn:harmonic:enrichment:aaa"])


@pytest.mark.asyncio
async def test_get_enrichment_status_reraises_on_http_error():
    with patch(HARMONIC_REQUEST, new=AsyncMock(return_value=_http_500())):
        with pytest.raises(aiohttp.ClientResponseError):
            await _client().get_enrichment_status(["urn:harmonic:enrichment:aaa"])


@pytest.mark.asyncio
@patch(PACE_SECONDS_HARMONIC, return_value=1.5)
@patch("ee.billing.salesforce_enrichment.harmonic_client.asyncio.sleep", new_callable=AsyncMock)
async def test_enrich_companies_batch_paces_once_for_the_whole_batch(mock_sleep, mock_pace):
    # Pacing must run once per batch, not once per domain: pacing inside each gathered task would
    # let every task's wait elapse in parallel, so the batch would still fire all at once.
    client = _client(priority=Priority.BATCH)
    mock_request = AsyncMock(side_effect=[_found({"name": "A"}), _found({"name": "B"})])
    with patch(HARMONIC_REQUEST, new=mock_request):
        results = await client.enrich_companies_batch(["a.com", "b.com"])
    assert results == [{"name": "A"}, {"name": "B"}]
    mock_sleep.assert_awaited_once_with(1.5)
    mock_pace.assert_called_once_with(Priority.BATCH)
