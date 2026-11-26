import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

from django.test import override_settings

import grpc.aio

from posthog.managed_proxy import cloudflare_proxy_lock
from posthog.models import Organization, ProxyRecord
from posthog.temporal.proxy_service.delete import (
    DeleteManagedProxyInputs,
    delete_cloudflare_proxy,
    delete_managed_proxy,
    record_proxy_deletion_failure,
)


class TestDeleteCloudflareProxy:
    @patch("posthog.temporal.proxy_service.delete.update_cloudflare_proxy_root_redirect")
    @patch("posthog.temporal.proxy_service.delete.get_custom_hostname_by_domain", return_value=None)
    async def test_clears_kv_even_when_no_root_redirect_is_configured(self, _get_hostname, update_redirect):
        inputs = DeleteManagedProxyInputs(
            organization_id=uuid.uuid4(),
            proxy_record_id=uuid.uuid4(),
            domain="test.example.com",
            root_redirect_url=None,
        )

        def clear_redirect(domain, url):
            competing_lock = cloudflare_proxy_lock(inputs.proxy_record_id)
            acquired = competing_lock.acquire(blocking=False)
            if acquired:
                competing_lock.release()
            assert not acquired

        update_redirect.side_effect = clear_redirect
        await delete_cloudflare_proxy(inputs)

        update_redirect.assert_called_once_with("test.example.com", None)


async def test_legacy_deletion_succeeds_when_resources_are_already_absent() -> None:
    provisioner = SimpleNamespace(
        Delete=AsyncMock(
            side_effect=grpc.aio.AioRpcError(grpc.StatusCode.NOT_FOUND, grpc.aio.Metadata(), grpc.aio.Metadata())
        )
    )
    inputs = DeleteManagedProxyInputs(
        organization_id=uuid.uuid4(), proxy_record_id=uuid.uuid4(), domain="test.example.com"
    )
    with patch("posthog.temporal.proxy_service.delete.get_grpc_client", return_value=provisioner):
        await delete_managed_proxy(inputs)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("target_cname", "expected_status"),
    [
        ("legacy.example.com", ProxyRecord.Status.ERRORING),
        ("test.proxy.example.com", ProxyRecord.Status.DELETING),
    ],
)
@override_settings(CLOUDFLARE_PROXY_BASE_CNAME="proxy.example.com")
async def test_failed_deletion_preserves_cloudflare_intent_and_allows_legacy_retry(
    target_cname: str, expected_status: str
) -> None:
    record = await ProxyRecord.objects.acreate(
        organization=await Organization.objects.acreate(name="Proxy test"),
        domain="analytics.example.com",
        target_cname=target_cname,
        status=ProxyRecord.Status.DELETING,
    )
    await record_proxy_deletion_failure(
        DeleteManagedProxyInputs(
            organization_id=record.organization_id,
            proxy_record_id=record.id,
            domain=record.domain,
            target_cname=target_cname,
        )
    )
    await record.arefresh_from_db()
    assert record.status == expected_status
    assert record.message == "Could not delete the proxy. Try again."
