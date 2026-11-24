import uuid
import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings

import responses
import temporalio.worker
from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from posthog.models import Organization, ProxyRecord
from posthog.models.proxy_record import CloudflareActivationState
from posthog.tasks.proxy import (
    PROXY_SWEEP_SPREAD_SECONDS,
    reconcile_managed_proxies,
    reconcile_proxy,
    reconcile_proxy_root_redirect,
)
from posthog.temporal.proxy_service.cloudflare import CloudflareAPIError
from posthog.temporal.proxy_service.common import (
    NonRetriableException,
    RecordDeletedException,
    SendProxyCreatedEmailInputs,
    UpdateProxyRecordInputs,
    activity_update_proxy_record,
)
from posthog.temporal.proxy_service.create import (
    CreateCloudflareProxyInputs,
    CreateManagedProxyInputs,
    CreateManagedProxyWorkflow,
    ScheduleMonitorJobInputs,
    WaitForCertificateInputs,
    WaitForDNSRecordsInputs,
    create_cloudflare_custom_hostname,
    wait_for_cloudflare_certificate,
)
from posthog.temporal.proxy_service.delete import DeleteManagedProxyInputs


class ProxyWorkflowTestClient:
    def __init__(self, running_retry_id: str | None = None) -> None:
        self.running_retry_id = running_retry_id
        self.started: dict[str, tuple[str, CreateManagedProxyInputs | DeleteManagedProxyInputs]] = {}

    async def list_workflows(self, *, query: str, limit: int, page_size: int) -> AsyncIterator[str]:
        if self.running_retry_id is not None:
            prefix = self.running_retry_id.rsplit("-", maxsplit=1)[0] + "-"
            if query == f'WorkflowId STARTS_WITH "{prefix}" AND ExecutionStatus = "Running"':
                yield self.running_retry_id

    async def start_workflow(
        self,
        name: str,
        inputs: CreateManagedProxyInputs | DeleteManagedProxyInputs,
        *,
        id: str,
        task_queue: str,
        id_conflict_policy: WorkflowIDConflictPolicy,
    ) -> None:
        self.started[id] = (name, inputs)


def _make_mock_activities(failing_activity: str | None = None, error_type: str = "NonRetriableException"):
    """Create mock activities for the Cloudflare create-proxy workflow path.

    Args:
        failing_activity: Name of the activity that should raise. None means all succeed.
        error_type: The exception type string for the ApplicationError.
    """
    status_updates: list[str] = []

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
        _maybe_raise("create_cloudflare_custom_hostname")

    @activity.defn(name="wait_for_cloudflare_certificate")
    async def mock_wait_cert(inputs: CreateCloudflareProxyInputs):
        _maybe_raise("wait_for_cloudflare_certificate")

    @activity.defn(name="create_managed_proxy")
    async def mock_create_legacy(inputs: CreateManagedProxyInputs) -> None:
        pass

    @activity.defn(name="wait_for_certificate")
    async def mock_wait_legacy_cert(inputs: WaitForCertificateInputs) -> None:
        pass

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
        mock_create_legacy,
        mock_wait_legacy_cert,
        mock_send_email,
        mock_schedule_monitor,
    ]

    return activities, status_updates


def _make_workflow_inputs():
    return CreateManagedProxyInputs(
        organization_id=uuid.uuid4(),
        proxy_record_id=uuid.uuid4(),
        domain="test.example.com",
        target_cname="target.example.com",
    )


class CloudflareProxyTestMixin:
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Proxy test")
        self.record = ProxyRecord.objects.create(
            organization=self.organization,
            domain="analytics.example.com",
            target_cname="test.proxy.example.com",
            status=ProxyRecord.Status.VALID,
            root_redirect_url="https://www.example.com/",
        )
        self.proxy_args = (str(self.organization.pk), str(self.record.pk))
        self.inputs = CreateCloudflareProxyInputs(self.organization.pk, self.record.pk, self.record.domain)
        self.hostnames_url = "https://api.cloudflare.com/client/v4/zones/test-zone/custom_hostnames"
        self.kv_url = "https://api.cloudflare.com/client/v4/accounts/test-account/storage/kv/namespaces/test-kv/values/analytics.example.com"
        self.hostname = {
            "id": "test-hostname",
            "hostname": self.record.domain,
            "status": "active",
            "ssl": {"status": "active"},
        }

    def _cloudflare(self, http: responses.RequestsMock, *, exists: bool) -> None:
        http.get(self.hostnames_url, json={"success": True, "result": [self.hostname] if exists else []})
        http.post(self.hostnames_url, json={"success": True, "result": self.hostname})
        http.delete(self.hostnames_url + "/test-hostname", json={"success": True, "result": {}})
        http.put(self.kv_url, json={"success": True, "result": {}})
        http.delete(self.kv_url, json={"success": True, "result": {}})


@override_settings(
    CLOUDFLARE_PROXY_BASE_CNAME="proxy.example.com",
    CLOUDFLARE_ZONE_ID="test-zone",
    CLOUDFLARE_API_TOKEN="test-token",
    CLOUDFLARE_PROXY_KV_NAMESPACE_ID="test-kv",
    CLOUDFLARE_ACCOUNT_ID="test-account",
)
class TestCloudflareProxyActivation(CloudflareProxyTestMixin, TestCase):
    @parameterized.expand([(True, None), (None, True)])
    def test_committed_activation_changes_keep_proxy_settings(self, before: bool | None, after: bool | None) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=before)
        with patch("posthog.tasks.proxy.reconcile_proxy.delay", side_effect=reconcile_proxy.run):
            for active, methods in ((False, ["GET", "DELETE", "DELETE"]), (after, ["GET", "POST", "PUT"])):
                with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
                    self._cloudflare(http, exists=active is False)
                    with self.captureOnCommitCallbacks(execute=True):
                        self.organization.is_active = active
                        self.organization.save(update_fields=["is_active"])
                        self.assertFalse(http.calls)
                    self.assertEqual([call.request.method for call in http.calls], methods)
                    if active is not False:
                        self.assertEqual(http.calls[-1].request.body, b"https://www.example.com/")

        self.record.refresh_from_db()
        self.assertEqual(self.record.status, ProxyRecord.Status.VALID)
        self.assertEqual(self.record.root_redirect_url, "https://www.example.com/")
        self.assertEqual(self.record.cloudflare_activation_state, CloudflareActivationState.IDLE)

    def test_rolled_back_activation_and_failed_publish(self) -> None:
        subsequent_hooks = []
        with (
            patch("posthog.tasks.proxy.reconcile_proxy.delay", side_effect=ConnectionError),
            patch("posthog.tasks.proxy.capture_exception"),
        ):
            with self.captureOnCommitCallbacks(execute=True) as rolled_back:
                with transaction.atomic():
                    self.organization.is_active = False
                    self.organization.save(update_fields=["is_active"])
                    transaction.set_rollback(True)
            self.assertEqual(rolled_back, [])
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.save(update_fields=["is_active"])
                transaction.on_commit(lambda: subsequent_hooks.append("completed"))

        self.assertEqual(subsequent_hooks, ["completed"])
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=True)
            self._sweep()
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE", "DELETE"])

    def _sweep(self) -> None:
        jobs = []

        def enqueue(*, args: tuple[str, str], countdown: int) -> None:
            self.assertIn(countdown, range(PROXY_SWEEP_SPREAD_SECONDS))
            jobs.append(args)

        with patch("posthog.tasks.proxy.reconcile_proxy.apply_async", new=enqueue):
            reconcile_managed_proxies.run()
        for args in jobs:
            reconcile_proxy.run(*args)

    @parameterized.expand([(ProxyRecord.Status.VALID,), (ProxyRecord.Status.ISSUING,), (ProxyRecord.Status.ERRORING,)])
    def test_sweep_resumes_suspended_proxies_after_monitor_errors(self, status: str) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
        ProxyRecord.objects.filter(pk=self.record.pk).update(status=status)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=True)
            self._sweep()
            self._sweep()
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE", "DELETE"])

        Organization.objects.filter(pk=self.organization.pk).update(is_active=True, is_pending_deletion=None)
        ProxyRecord.objects.filter(pk=self.record.pk).update(status=ProxyRecord.Status.ERRORING)
        temporal = ProxyWorkflowTestClient()
        with responses.RequestsMock(), patch("posthog.tasks.proxy.async_connect", return_value=temporal):
            self._sweep()

        [workflow_id] = temporal.started
        self.assertEqual(workflow_id, f"proxy-create-{self.record.id}")
        name, inputs = temporal.started[workflow_id]
        self.assertEqual(name, "create-proxy")
        self.assertIsInstance(inputs, CreateManagedProxyInputs)
        assert isinstance(inputs, CreateManagedProxyInputs)
        self.assertTrue(inputs.use_cloudflare)
        self.record.refresh_from_db()
        self.assertEqual(self.record.cloudflare_activation_state, CloudflareActivationState.SUSPENDED)

    @parameterized.expand(
        [
            (
                ProxyRecord.Status.VALID,
                CloudflareActivationState.IDLE,
                "test.proxy.example.com",
                "analytics.example.com",
            ),
            (
                ProxyRecord.Status.ERRORING,
                CloudflareActivationState.IDLE,
                "test.proxy.example.com",
                "analytics.example.com",
            ),
            (
                ProxyRecord.Status.TIMED_OUT,
                CloudflareActivationState.SUSPENDED,
                "test.proxy.example.com",
                "analytics.example.com",
            ),
            (
                ProxyRecord.Status.VALID,
                CloudflareActivationState.SUSPENDED,
                "legacy.example.com",
                "analytics.example.com",
            ),
            (
                ProxyRecord.Status.ERRORING,
                CloudflareActivationState.SUSPENDED,
                "test.proxy.example.com",
                "analytics.posthog.com",
            ),
        ]
    )
    def test_reconciliation_skips_unavailable_or_unaffected_proxies(
        self, status: str, state: CloudflareActivationState, cname: str, domain: str
    ) -> None:
        ProxyRecord.objects.filter(pk=self.record.pk).update(
            status=status, cloudflare_activation_state=state, target_cname=cname, domain=domain
        )
        temporal = ProxyWorkflowTestClient()
        with responses.RequestsMock() as http, patch("posthog.tasks.proxy.async_connect", return_value=temporal):
            reconcile_proxy.run(*self.proxy_args)
            self._sweep()
            self.assertFalse(http.calls)
        self.assertEqual(temporal.started, {})

    def test_pending_organization_deletion_prevents_proxy_and_redirect_restoration(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=True, is_pending_deletion=True)
        ProxyRecord.objects.filter(pk=self.record.pk).update(
            cloudflare_activation_state=CloudflareActivationState.SUSPENDED
        )
        with responses.RequestsMock() as http:
            reconcile_proxy.run(*self.proxy_args)
            reconcile_proxy_root_redirect.run(str(self.record.pk))
            self._sweep()
            self.assertFalse(http.calls)

    @parameterized.expand([(False,), (True,)])
    def test_suspension_preserves_recovery_across_partial_cleanup(self, previously_provisioned: bool) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
        ProxyRecord.objects.filter(pk=self.record.pk).update(status=ProxyRecord.Status.ERRORING)
        with responses.RequestsMock() as http:
            http.get(
                self.hostnames_url, json={"success": True, "result": [self.hostname] if previously_provisioned else []}
            )
            if previously_provisioned:
                http.delete(self.hostnames_url + "/test-hostname", json={"success": True, "result": {}})
            http.delete(self.kv_url, status=503, json={"success": False, "errors": []})
            with self.assertRaises(CloudflareAPIError):
                self._sweep()

        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            self._sweep()
            self._sweep()
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE"])

        self.record.refresh_from_db()
        self.assertEqual(
            self.record.cloudflare_activation_state,
            CloudflareActivationState.SUSPENDED if previously_provisioned else CloudflareActivationState.DEPROVISIONED,
        )

    def test_sweep_joins_running_retry(self) -> None:
        ProxyRecord.objects.filter(pk=self.record.pk).update(status=ProxyRecord.Status.ISSUING)
        temporal = ProxyWorkflowTestClient(running_retry_id=f"proxy-create-{self.record.id}-retry-1234")
        with patch("posthog.tasks.proxy.async_connect", return_value=temporal):
            self._sweep()
        self.assertEqual(temporal.started, {})

    def test_deletion_cleans_up_during_temporal_outage_and_resumes_when_available(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
        ProxyRecord.objects.filter(pk=self.record.pk).update(status=ProxyRecord.Status.DELETING)

        async def stall() -> None:
            await asyncio.Future()

        with (
            responses.RequestsMock(assert_all_requests_are_fired=False) as http,
            patch("posthog.tasks.proxy.PROXY_RECOVERY_TIMEOUT_SECONDS", 0),
            patch("posthog.tasks.proxy.async_connect", new=stall),
        ):
            self._cloudflare(http, exists=True)
            with self.assertRaises(TimeoutError):
                self._sweep()
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE", "DELETE"])

        temporal = ProxyWorkflowTestClient()
        with responses.RequestsMock() as http, patch("posthog.tasks.proxy.async_connect", return_value=temporal):
            self._sweep()
            self.assertFalse(http.calls)
        self.assertEqual(list(temporal.started), [f"proxy-delete-{self.record.id}"])

    @parameterized.expand([(False, ProxyRecord.Status.VALID), (True, ProxyRecord.Status.DELETING)])
    def test_redirect_job_does_not_restore_an_unavailable_proxy(self, active: bool, status: str) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=active)
        ProxyRecord.objects.filter(pk=self.record.pk).update(status=status)
        with responses.RequestsMock() as http:
            reconcile_proxy_root_redirect.run(str(self.record.pk))
            self.assertFalse(http.calls)


@override_settings(
    CLOUDFLARE_PROXY_BASE_CNAME="proxy.example.com",
    CLOUDFLARE_ZONE_ID="test-zone",
    CLOUDFLARE_API_TOKEN="test-token",
    CLOUDFLARE_PROXY_KV_NAMESPACE_ID="test-kv",
    CLOUDFLARE_ACCOUNT_ID="test-account",
)
class TestCloudflareProxyActivities(CloudflareProxyTestMixin, TransactionTestCase):
    @parameterized.expand([(False, CloudflareActivationState.SUSPENDED), (True, CloudflareActivationState.IDLE)])
    async def test_certificate_check_only_restores_active_suspended_proxies(
        self, active: bool, state: CloudflareActivationState
    ) -> None:
        await ProxyRecord.objects.filter(pk=self.record.pk).aupdate(
            status=ProxyRecord.Status.ISSUING, cloudflare_activation_state=state
        )
        await Organization.objects.filter(pk=self.organization.pk).aupdate(is_active=active)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            with self.assertRaises(NonRetriableException):
                await wait_for_cloudflare_certificate(self.inputs)
            self.assertEqual([call.request.method for call in http.calls], ["GET"])

    @parameterized.expand([(ProxyRecord.Status.ERRORING,), (ProxyRecord.Status.VALID,)])
    async def test_background_status_updates_preserve_deletion_intent(self, status: str) -> None:
        await ProxyRecord.objects.filter(pk=self.record.pk).aupdate(status=ProxyRecord.Status.DELETING)

        with self.assertRaises(RecordDeletedException):
            await activity_update_proxy_record(
                UpdateProxyRecordInputs(
                    organization_id=self.organization.id,
                    proxy_record_id=self.record.id,
                    status=status,
                )
            )

        await self.record.arefresh_from_db()
        self.assertEqual(self.record.status, ProxyRecord.Status.DELETING)

    @parameterized.expand([(False,), (True,)])
    async def test_recovery_waits_for_final_status_and_preserves_deactivation(self, deactivate: bool) -> None:
        await ProxyRecord.objects.filter(pk=self.record.pk).aupdate(
            status=ProxyRecord.Status.ISSUING, cloudflare_activation_state=CloudflareActivationState.SUSPENDED
        )
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            with self.assertRaisesRegex(ApplicationError, "waiting for a certificate"):
                await wait_for_cloudflare_certificate(self.inputs)
            self.assertEqual([call.request.method for call in http.calls], ["GET", "GET", "POST", "PUT"])

        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=True)
            await wait_for_cloudflare_certificate(self.inputs)

        await self.record.arefresh_from_db()
        self.assertEqual(self.record.cloudflare_activation_state, CloudflareActivationState.RECOVERY_PENDING)
        if deactivate:
            await Organization.objects.filter(pk=self.organization.pk).aupdate(is_active=False)
            with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
                self._cloudflare(http, exists=True)
                await sync_to_async(reconcile_proxy.run)(*self.proxy_args)

        with (
            responses.RequestsMock(assert_all_requests_are_fired=False) as http,
            patch.object(reconcile_proxy, "delay", side_effect=reconcile_proxy.run),
        ):
            self._cloudflare(http, exists=True)
            await activity_update_proxy_record(
                UpdateProxyRecordInputs(self.organization.pk, self.record.pk, ProxyRecord.Status.VALID)
            )
        await self.record.arefresh_from_db()
        expected_state = CloudflareActivationState.SUSPENDED if deactivate else CloudflareActivationState.IDLE
        self.assertEqual(self.record.cloudflare_activation_state, expected_state)

    async def test_delayed_valid_status_does_not_skip_hostname_restoration(self) -> None:
        organization = Organization.objects.filter(pk=self.organization.pk)
        await organization.aupdate(is_active=False)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=True)
            http.replace(responses.DELETE, self.kv_url, status=503, json={"success": False})
            with self.assertRaises(CloudflareAPIError):
                await sync_to_async(reconcile_proxy.run)(*self.proxy_args)
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE", "DELETE"])

        await organization.aupdate(is_active=True)
        queued = []
        with patch.object(reconcile_proxy, "delay", side_effect=lambda *args: queued.append(args)):
            await activity_update_proxy_record(
                UpdateProxyRecordInputs(self.organization.pk, self.record.pk, ProxyRecord.Status.VALID)
            )

        await self.record.arefresh_from_db()
        self.assertEqual(self.record.cloudflare_activation_state, CloudflareActivationState.RECOVERY_PENDING)
        self.assertEqual(queued, [self.proxy_args])

        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            await sync_to_async(reconcile_proxy.run)(*queued[0])
            self.assertEqual([call.request.method for call in http.calls], ["GET", "POST", "PUT"])

        await self.record.arefresh_from_db()
        self.assertEqual(self.record.cloudflare_activation_state, CloudflareActivationState.IDLE)

    @parameterized.expand([(True, False), (True, None), (False, False), (True, True)])
    async def test_creation_respects_organization_activation(self, active: bool, pending_deletion: bool | None) -> None:
        await ProxyRecord.objects.filter(pk=self.record.pk).aupdate(root_redirect_url=None)
        await Organization.objects.filter(pk=self.organization.pk).aupdate(
            is_active=active, is_pending_deletion=pending_deletion
        )
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            if active and not pending_deletion:
                await create_cloudflare_custom_hostname(self.inputs)
                self.assertEqual([call.request.method for call in http.calls], ["GET", "POST"])
            else:
                with self.assertRaises(RecordDeletedException):
                    await create_cloudflare_custom_hostname(self.inputs)
                self.assertFalse(http.calls)


@pytest.mark.django_db(transaction=True)
@patch("posthog.temporal.proxy_service.create.use_cloudflare_proxy", return_value=True)
class TestCreateManagedProxyWorkflowErrorHandling:
    @pytest.mark.parametrize(
        "failing_activity",
        [
            "create_cloudflare_custom_hostname",
            "wait_for_cloudflare_certificate",
        ],
    )
    async def test_activity_error_sets_erroring_status(self, _mock_cloudflare, failing_activity):
        activities, status_updates = _make_mock_activities(failing_activity=failing_activity)
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
        activities, status_updates = _make_mock_activities(
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

    @pytest.mark.parametrize(
        ("cloudflare_enabled", "target_cname", "backend", "expected_activity"),
        [
            (True, "test.legacy.example.com", False, "create_managed_proxy"),
            (False, "test.proxy.example.com", True, "create_cloudflare_custom_hostname"),
            (False, "test.proxy.example.com", None, "create_managed_proxy"),
        ],
    )
    @override_settings(CLOUDFLARE_PROXY_BASE_CNAME="proxy.example.com")
    async def test_happy_path_sets_valid_status(
        self, _mock_cloudflare, cloudflare_enabled, target_cname, backend, expected_activity, caplog
    ):
        caplog.set_level(logging.INFO, logger="temporalio.activity")
        caplog.set_level(logging.INFO, logger="temporalio.workflow")
        _mock_cloudflare.return_value = cloudflare_enabled
        activities, status_updates = _make_mock_activities()
        task_queue = str(uuid.uuid4())
        inputs = _make_workflow_inputs()
        inputs.target_cname = target_cname
        inputs.use_cloudflare = backend
        payload = asdict(inputs)
        if backend is None:
            del payload["use_cloudflare"]

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[CreateManagedProxyWorkflow],
                activities=activities,
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    "create-proxy",
                    payload,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=timedelta(seconds=30),
                )
                await handle.result()
                history = await handle.fetch_history()

        assert "valid" in status_updates
        assert "erroring" not in status_updates
        assert any(
            event.activity_task_scheduled_event_attributes.activity_type.name == expected_activity
            for event in history.events
        )
        if backend is not None:
            _mock_cloudflare.return_value = backend
        await Replayer(
            workflows=[CreateManagedProxyWorkflow],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ).replay_workflow(history)

    async def test_email_failure_does_not_fail_workflow(self, _mock_cloudflare):
        activities, status_updates = _make_mock_activities(failing_activity="activity_send_proxy_created_email")
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
