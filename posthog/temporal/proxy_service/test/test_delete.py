import uuid

import pytest
from unittest.mock import patch

from django.test import override_settings

import grpc.aio
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.managed_proxy import cloudflare_proxy_lock
from posthog.models import Organization, ProxyRecord
from posthog.temporal.proxy_service.common import NonRetriableException
from posthog.temporal.proxy_service.delete import (
    DeleteManagedProxyInputs,
    DeleteManagedProxyWorkflow,
    delete_cloudflare_proxy,
    delete_managed_proxy,
    delete_proxy_record,
    record_proxy_deletion_failure,
)
from posthog.temporal.proxy_service.proto import DeleteRequest


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("cloudflare", "legacy_error", "remaining_status"),
    [
        (False, grpc.StatusCode.NOT_FOUND, None),
        (False, grpc.StatusCode.INVALID_ARGUMENT, ProxyRecord.Status.ERRORING),
        (True, None, ProxyRecord.Status.DELETING),
    ],
)
@override_settings(CLOUDFLARE_PROXY_BASE_CNAME="proxy.example.com")
async def test_delete_workflow_handles_missing_resources_and_failed_cleanup(
    cloudflare: bool, legacy_error: grpc.StatusCode | None, remaining_status: str | None
) -> None:
    organization = await Organization.objects.acreate(name="Proxy test")
    record = await ProxyRecord.objects.acreate(
        organization=organization,
        domain="analytics.example.com",
        target_cname="test.proxy.example.com" if cloudflare else "legacy.example.com",
        status=ProxyRecord.Status.DELETING,
    )
    inputs = DeleteManagedProxyInputs(
        organization_id=organization.id,
        proxy_record_id=record.id,
        domain=record.domain,
        target_cname=record.target_cname,
    )

    class LegacyProvisioner:
        async def Delete(self, _request: DeleteRequest) -> None:
            assert legacy_error is not None
            raise grpc.aio.AioRpcError(legacy_error, grpc.aio.Metadata(), grpc.aio.Metadata())

    @activity.defn(name="delete_cloudflare_proxy")
    async def fail_cloudflare_deletion(_inputs: DeleteManagedProxyInputs) -> None:
        raise NonRetriableException("Could not reach Cloudflare")

    task_queue = str(uuid.uuid4())
    with patch("posthog.temporal.proxy_service.delete.get_grpc_client", return_value=LegacyProvisioner()):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[DeleteManagedProxyWorkflow],
                activities=[
                    delete_managed_proxy,
                    fail_cloudflare_deletion,
                    delete_proxy_record,
                    record_proxy_deletion_failure,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    DeleteManagedProxyWorkflow.run, inputs, id=str(uuid.uuid4()), task_queue=task_queue
                )
                if remaining_status is None:
                    await handle.result()
                else:
                    with pytest.raises(WorkflowFailureError):
                        await handle.result()

    remaining = await ProxyRecord.objects.filter(pk=record.pk).afirst()
    if remaining_status is None:
        assert remaining is None
    else:
        assert remaining is not None
        assert remaining.status == remaining_status
        assert remaining.message == "Could not delete the proxy. Try again."
