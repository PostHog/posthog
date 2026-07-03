import uuid

import pytest
from unittest.mock import patch

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.proxy_service.common import SendProxyCreatedEmailInputs, UpdateProxyRecordInputs
from posthog.temporal.proxy_service.create import (
    CreateCloudflareProxyInputs,
    CreateManagedProxyInputs,
    CreateManagedProxyWorkflow,
    ScheduleMonitorJobInputs,
    WaitForCertificateInputs,
    WaitForDNSRecordsInputs,
)


def _make_mock_activities(failing_activity: str | None = None, error_type: str = "NonRetriableException"):
    """Create mock activities for the Cloudflare create-proxy workflow path.

    Args:
        failing_activity: Name of the activity that should raise. None means all succeed.
        error_type: The exception type string for the ApplicationError.
    """
    status_updates: list[str] = []
    called: list[str] = []

    def _maybe_raise(activity_name: str):
        if activity_name == failing_activity:
            raise ApplicationError(
                f"Mock error in {activity_name}",
                type=error_type,
                non_retryable=True,
            )

    @activity.defn(name="wait_for_dns_records")
    async def mock_wait_for_dns(inputs: WaitForDNSRecordsInputs):
        pass

    @activity.defn(name="activity_update_proxy_record")
    async def mock_update_record(inputs: UpdateProxyRecordInputs):
        status_updates.append(inputs.status)

    @activity.defn(name="create_cloudflare_custom_hostname")
    async def mock_create_hostname(inputs: CreateCloudflareProxyInputs):
        called.append("create_cloudflare_custom_hostname")
        _maybe_raise("create_cloudflare_custom_hostname")

    @activity.defn(name="wait_for_cloudflare_certificate")
    async def mock_wait_cert(inputs: CreateCloudflareProxyInputs):
        called.append("wait_for_cloudflare_certificate")
        _maybe_raise("wait_for_cloudflare_certificate")

    @activity.defn(name="create_managed_proxy")
    async def mock_create_managed_proxy(inputs: CreateManagedProxyInputs):
        called.append("create_managed_proxy")
        _maybe_raise("create_managed_proxy")

    @activity.defn(name="wait_for_certificate")
    async def mock_wait_for_certificate(inputs: WaitForCertificateInputs):
        called.append("wait_for_certificate")
        _maybe_raise("wait_for_certificate")

    @activity.defn(name="activity_send_proxy_created_email")
    async def mock_send_email(inputs: SendProxyCreatedEmailInputs):
        _maybe_raise("activity_send_proxy_created_email")

    @activity.defn(name="schedule_monitor_job")
    async def mock_schedule_monitor(inputs: ScheduleMonitorJobInputs):
        pass

    activities = [
        mock_wait_for_dns,
        mock_update_record,
        mock_create_hostname,
        mock_wait_cert,
        mock_create_managed_proxy,
        mock_wait_for_certificate,
        mock_send_email,
        mock_schedule_monitor,
    ]

    return activities, status_updates, called


def _make_workflow_inputs(target_cname: str = "target.example.com"):
    return CreateManagedProxyInputs(
        organization_id=uuid.uuid4(),
        proxy_record_id=uuid.uuid4(),
        domain="test.example.com",
        target_cname=target_cname,
    )


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.proxy_service.create.is_cloudflare_proxy_by_cname", return_value=True)
class TestCreateManagedProxyWorkflowErrorHandling:
    @pytest.mark.parametrize(
        "failing_activity",
        [
            "create_cloudflare_custom_hostname",
            "wait_for_cloudflare_certificate",
        ],
    )
    async def test_activity_error_sets_erroring_status(self, _mock_cloudflare, failing_activity):
        activities, status_updates, _called = _make_mock_activities(failing_activity=failing_activity)
        task_queue = str(uuid.uuid4())

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[CreateManagedProxyWorkflow],
                activities=activities,
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(WorkflowFailureError):
                    await env.client.execute_workflow(
                        CreateManagedProxyWorkflow.run,
                        _make_workflow_inputs(),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

        assert "erroring" in status_updates

    async def test_record_deleted_exception_returns_without_error(self, _mock_cloudflare):
        activities, status_updates, _called = _make_mock_activities(
            failing_activity="create_cloudflare_custom_hostname",
            error_type="RecordDeletedException",
        )
        task_queue = str(uuid.uuid4())

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[CreateManagedProxyWorkflow],
                activities=activities,
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    CreateManagedProxyWorkflow.run,
                    _make_workflow_inputs(),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert "erroring" not in status_updates

    async def test_happy_path_sets_valid_status(self, _mock_cloudflare):
        activities, status_updates, _called = _make_mock_activities()
        task_queue = str(uuid.uuid4())

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[CreateManagedProxyWorkflow],
                activities=activities,
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    CreateManagedProxyWorkflow.run,
                    _make_workflow_inputs(),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert "valid" in status_updates
        assert "erroring" not in status_updates

    async def test_email_failure_does_not_fail_workflow(self, _mock_cloudflare):
        activities, status_updates, _called = _make_mock_activities(
            failing_activity="activity_send_proxy_created_email"
        )
        task_queue = str(uuid.uuid4())

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[CreateManagedProxyWorkflow],
                activities=activities,
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    CreateManagedProxyWorkflow.run,
                    _make_workflow_inputs(),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert "valid" in status_updates
        assert "erroring" not in status_updates


@pytest.mark.django_db(transaction=True)
class TestCreateManagedProxyWorkflowPathSelection:
    """The provisioning path must follow the record's target_cname, not the global flag, so a
    retry never migrates a legacy proxy onto Cloudflare after the flag is enabled globally."""

    @pytest.mark.parametrize(
        "target_cname,expected,forbidden",
        [
            ("digest.cf-base.example.com", "create_cloudflare_custom_hostname", "create_managed_proxy"),
            # Legacy target while the global flag is ON — must still take the legacy path.
            ("digest.legacy-base.example.com", "create_managed_proxy", "create_cloudflare_custom_hostname"),
        ],
    )
    async def test_path_follows_target_cname_not_global_flag(self, settings, target_cname, expected, forbidden):
        settings.CLOUDFLARE_PROXY_BASE_CNAME = "cf-base.example.com"
        settings.CLOUDFLARE_PROXY_ENABLED = True  # flag on — but the target_cname must decide the path
        activities, _status_updates, called = _make_mock_activities()
        task_queue = str(uuid.uuid4())

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[CreateManagedProxyWorkflow],
                activities=activities,
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    CreateManagedProxyWorkflow.run,
                    _make_workflow_inputs(target_cname=target_cname),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert expected in called
        assert forbidden not in called
