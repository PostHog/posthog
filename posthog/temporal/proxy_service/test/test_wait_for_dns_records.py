import uuid

import pytest
from unittest.mock import AsyncMock, patch

import dns.resolver

from posthog.temporal.proxy_service.common import NonRetriableException
from posthog.temporal.proxy_service.create import WaitForDNSRecordsInputs, wait_for_dns_records


@pytest.fixture
def dns_input():
    return WaitForDNSRecordsInputs(
        organization_id=uuid.uuid4(),
        proxy_record_id=uuid.uuid4(),
        domain="proxy.example.com",
        target_cname="us.i.posthog.com",
    )


@pytest.mark.asyncio
@patch("posthog.temporal.proxy_service.create.update_record", new_callable=AsyncMock)
@patch("posthog.temporal.proxy_service.create.record_exists", new_callable=AsyncMock, return_value=True)
@patch("posthog.temporal.proxy_service.create.dns.asyncresolver.resolve")
async def test_servfail_is_retriable_not_non_retriable(
    mock_resolve, _mock_record_exists, mock_update_record, dns_input
):
    mock_resolve.side_effect = dns.resolver.NoNameservers("SERVFAIL")

    with pytest.raises(dns.resolver.NoNameservers):
        await wait_for_dns_records(dns_input)

    mock_update_record.assert_awaited_once()
    assert "nameserver" in mock_update_record.call_args.kwargs["message"].lower()


@pytest.mark.asyncio
@patch("posthog.temporal.proxy_service.create.record_exists", new_callable=AsyncMock, return_value=True)
@patch("posthog.temporal.proxy_service.create.dns.asyncresolver.resolve")
async def test_unexpected_error_is_non_retriable(mock_resolve, _mock_record_exists, dns_input):
    mock_resolve.side_effect = ValueError("boom")

    with pytest.raises(NonRetriableException):
        await wait_for_dns_records(dns_input)
