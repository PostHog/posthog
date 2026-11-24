import uuid
import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import timedelta

import pytest
from unittest.mock import patch

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings

import responses
import temporalio.worker
from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from posthog.managed_proxy import cloudflare_proxy_lock
from posthog.models import Organization, ProxyRecord
from posthog.tasks.proxy import (
    PROXY_SWEEP_SPREAD_SECONDS,
    reconcile_managed_proxies,
    reconcile_proxy,
    reconcile_proxy_root_redirect,
)
from posthog.temporal.proxy_service.common import (
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
    @parameterized.expand(
        [
            (True, False),
            (None, False),
            (False, True),
            (False, None),
            (True, False, ProxyRecord.Status.WAITING),
        ]
    )
    def test_activation_changes_reconcile_after_commit_and_keep_customer_settings(
        self, previous: bool | None, current: bool | None, status: str = ProxyRecord.Status.VALID
    ) -> None:
        self.record.status = status
        self.record.save(update_fields=["status"])
        Organization.objects.filter(pk=self.organization.pk).update(is_active=previous)
        self.organization.is_active = current

        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=current is False)
            with patch("posthog.tasks.proxy.reconcile_proxy.delay", side_effect=reconcile_proxy.run):
                with self.captureOnCommitCallbacks(execute=True):
                    self.organization.save(update_fields=["is_active"])
                    self.assertEqual(len(http.calls), 0)

            self.assertEqual(
                [(call.request.method, call.request.url.split("?")[0]) for call in http.calls],
                [
                    ("GET", self.hostnames_url),
                    ("DELETE", self.hostnames_url + "/test-hostname"),
                    ("DELETE", self.kv_url),
                ]
                if current is False
                else [("GET", self.hostnames_url), ("POST", self.hostnames_url), ("PUT", self.kv_url)],
            )
            if current is not False:
                self.assertEqual(http.calls[-1].request.body, b"https://www.example.com/")

        self.record.refresh_from_db()
        self.assertEqual(self.record.status, status)
        self.assertEqual(self.record.root_redirect_url, "https://www.example.com/")

    @parameterized.expand([(False, True), (False, False), (True, False), (True, True), (None, False)])
    def test_delayed_job_uses_current_organization_state(self, current: bool | None, exists: bool) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=current)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=exists)
            reconcile_proxy.run(str(self.organization.pk), str(self.record.pk))
            self.assertEqual(http.calls[-1].request.method, "DELETE" if current is False else "PUT")

    @parameterized.expand([("unchanged",), ("unrelated_save",), ("rollback",)])
    def test_saves_without_committed_activation_changes_do_not_reconcile(self, scenario: str) -> None:
        with patch("posthog.tasks.proxy.reconcile_proxy.delay", side_effect=reconcile_proxy.run):
            with responses.RequestsMock() as http:
                with self.captureOnCommitCallbacks(execute=True):
                    if scenario == "rollback":
                        with transaction.atomic():
                            self.organization.is_active = False
                            self.organization.save(update_fields=["is_active"])
                            transaction.set_rollback(True)
                    elif scenario == "unrelated_save":
                        self.organization.is_active = False
                        self.organization.save(update_fields=["name"])
                    else:
                        self.organization.save(update_fields=["is_active"])
                self.assertEqual(len(http.calls), 0)

    @parameterized.expand(
        [("legacy",), ("missing",), ("waiting",), ("timed_out",), ("reserved",), ("reserved_erroring",)]
    )
    def test_reconciliation_does_not_provision_unavailable_records(self, scenario: str) -> None:
        record_id = str(self.record.pk)
        if scenario == "missing":
            self.record.delete()
        elif scenario.startswith("reserved"):
            self.record.domain = "analytics.posthog.com"
            if scenario == "reserved_erroring":
                self.record.status = ProxyRecord.Status.ERRORING
            self.record.save(update_fields=["domain", "status"])
        elif scenario == "legacy":
            self.record.target_cname = "legacy.example.com"
            self.record.save(update_fields=["target_cname"])
        else:
            self.record.status = scenario
            self.record.save(update_fields=["status"])
        temporal = ProxyWorkflowTestClient()
        with responses.RequestsMock() as http, patch("posthog.tasks.proxy.async_connect", return_value=temporal):
            reconcile_proxy.run(str(self.organization.pk), record_id)
            self.assertEqual(len(http.calls), 0)
        self.assertEqual(temporal.started, {})

    def test_deprovisioning_is_idempotent_when_hostname_is_already_absent(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            reconcile_proxy.run(str(self.organization.pk), str(self.record.pk))
            reconcile_proxy.run(str(self.organization.pk), str(self.record.pk))
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE"])
        self.record.refresh_from_db()
        self.assertTrue(self.record.cloudflare_deprovisioned)

    @parameterized.expand([(False, ProxyRecord.Status.VALID), (True, ProxyRecord.Status.DELETING)])
    def test_redirect_job_does_not_restore_an_unavailable_proxy(self, active: bool, status: str) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=active)
        ProxyRecord.objects.filter(pk=self.record.pk).update(status=status)
        with responses.RequestsMock() as http:
            reconcile_proxy_root_redirect.run(str(self.record.pk))
            self.assertEqual(len(http.calls), 0)

    @parameterized.expand([(ProxyRecord.Status.ISSUING,), (ProxyRecord.Status.ERRORING,)])
    def test_reactivation_resumes_incomplete_provisioning(self, status: str) -> None:
        self.record.status = status
        self.record.save(update_fields=["status"])
        temporal = ProxyWorkflowTestClient()
        with responses.RequestsMock() as http, patch("posthog.tasks.proxy.async_connect", return_value=temporal):
            reconcile_proxy.run(str(self.organization.pk), str(self.record.pk))
            self.assertEqual(len(http.calls), 0)
        self.assertEqual(
            temporal.started,
            {
                f"proxy-create-{self.record.id}": (
                    "create-proxy",
                    CreateManagedProxyInputs(
                        organization_id=self.organization.id,
                        proxy_record_id=self.record.id,
                        domain=self.record.domain,
                        target_cname=self.record.target_cname,
                        use_cloudflare=True,
                    ),
                )
            },
        )

    def test_reconciliation_leaves_a_running_timestamped_retry_in_place(self) -> None:
        ProxyRecord.objects.filter(pk=self.record.pk).update(status=ProxyRecord.Status.ISSUING)
        workflow_id = f"proxy-create-{self.record.id}-retry-1234"
        temporal = ProxyWorkflowTestClient(running_retry_id=workflow_id)

        with patch("posthog.tasks.proxy.async_connect", return_value=temporal):
            reconcile_proxy.run(str(self.organization.pk), str(self.record.pk))

        self.assertEqual(temporal.started, {})

    @parameterized.expand([(ProxyRecord.Status.ISSUING,), (ProxyRecord.Status.DELETING,)])
    def test_sweep_recovers_after_a_temporal_connection_timeout(self, record_status: str) -> None:
        self.record.status = record_status
        self.record.save(update_fields=["status"])

        async def stalled_connection() -> None:
            await asyncio.Future()

        with (
            patch("posthog.tasks.proxy.PROXY_RECOVERY_TIMEOUT_SECONDS", 0),
            patch("posthog.tasks.proxy.async_connect", side_effect=stalled_connection),
            self.assertRaises(TimeoutError),
        ):
            reconcile_proxy.run(str(self.organization.pk), str(self.record.pk))

        self.record.refresh_from_db()
        self.assertEqual(self.record.status, record_status)
        with cloudflare_proxy_lock(self.record.id):
            self.assertTrue(ProxyRecord.objects.filter(pk=self.record.pk).exists())

    def test_hourly_sweep_spreads_recovery_and_skips_healthy_and_failed_proxies(self) -> None:
        self.record.status = ProxyRecord.Status.ERRORING
        self.record.save(update_fields=["status"])
        ProxyRecord.objects.create(
            organization=self.organization,
            domain="healthy.example.com",
            target_cname="healthy.proxy.example.com",
            status=ProxyRecord.Status.VALID,
        )
        interrupted = ProxyRecord.objects.create(
            organization=self.organization,
            domain="interrupted.example.com",
            target_cname="interrupted.proxy.example.com",
            status=ProxyRecord.Status.ISSUING,
        )
        dispatched: dict[tuple[str, str], tuple[dict[str, bool], int]] = {}

        def capture_job(*, args: tuple[str, str], kwargs: dict[str, bool], countdown: int) -> None:
            dispatched[args] = (kwargs, countdown)

        with patch("posthog.tasks.proxy.reconcile_proxy.apply_async", new=capture_job):
            reconcile_managed_proxies.run()

        [job] = dispatched
        self.assertEqual(job, (str(self.organization.pk), str(interrupted.pk)))
        options, countdown = dispatched[job]
        self.assertEqual(options, {"from_sweep": True})
        self.assertIn(countdown, range(PROXY_SWEEP_SPREAD_SECONDS))

        temporal = ProxyWorkflowTestClient()
        with patch("posthog.tasks.proxy.async_connect", return_value=temporal):
            reconcile_proxy.run(str(self.organization.pk), str(self.record.pk), from_sweep=True)
        self.assertEqual(temporal.started, {})

    def test_hourly_sweep_recovers_suspended_proxy_after_monitor_error_and_missed_enqueue(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=True)
            reconcile_proxy.run(str(self.organization.pk), str(self.record.pk))
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE", "DELETE"])

        self.record.refresh_from_db()
        self.assertTrue(self.record.needs_activation_recovery)
        self.assertTrue(self.record.cloudflare_deprovisioned)
        with (
            responses.RequestsMock() as http,
            patch(
                "posthog.tasks.proxy.reconcile_proxy.apply_async",
                side_effect=lambda args, kwargs, countdown: reconcile_proxy.run(*args, **kwargs),
            ),
        ):
            reconcile_managed_proxies.run()
            self.assertEqual(len(http.calls), 0)

        ProxyRecord.objects.filter(pk=self.record.pk).update(status=ProxyRecord.Status.ERRORING)
        Organization.objects.filter(pk=self.organization.pk).update(is_active=True)
        temporal = ProxyWorkflowTestClient()

        with (
            patch("posthog.tasks.proxy.async_connect", return_value=temporal),
            patch(
                "posthog.tasks.proxy.reconcile_proxy.apply_async",
                side_effect=lambda args, kwargs, countdown: reconcile_proxy.run(*args, **kwargs),
            ),
        ):
            reconcile_managed_proxies.run()
            self.assertEqual(list(temporal.started), [f"proxy-create-{self.record.id}"])
            temporal.started.clear()
            reconcile_managed_proxies.run()

        self.record.refresh_from_db()
        self.assertTrue(self.record.needs_activation_recovery)
        self.assertEqual(list(temporal.started), [f"proxy-create-{self.record.id}"])

    @parameterized.expand([(ProxyRecord.Status.ERRORING,), (ProxyRecord.Status.VALID,)])
    def test_background_status_updates_preserve_deletion_intent(self, status: str) -> None:
        self.record.status = ProxyRecord.Status.DELETING
        self.record.save(update_fields=["status"])

        with self.assertRaises(RecordDeletedException):
            async_to_sync(activity_update_proxy_record)(
                UpdateProxyRecordInputs(
                    organization_id=self.organization.id,
                    proxy_record_id=self.record.id,
                    status=status,
                )
            )

        self.record.refresh_from_db()
        self.assertEqual(self.record.status, ProxyRecord.Status.DELETING)

    @parameterized.expand(
        [
            (False, "test.proxy.example.com"),
            (True, "test.proxy.example.com"),
            (None, "test.proxy.example.com"),
            (True, "legacy.example.com"),
        ]
    )
    def test_sweep_resumes_deletion_instead_of_provisioning(self, active: bool | None, target_cname: str) -> None:
        self.record.status = ProxyRecord.Status.DELETING
        self.record.target_cname = target_cname
        self.record.save(update_fields=["status", "target_cname"])
        Organization.objects.filter(pk=self.organization.pk).update(is_active=active)
        temporal = ProxyWorkflowTestClient()

        async def connect_while_deleting() -> ProxyWorkflowTestClient:
            competing_lock = cloudflare_proxy_lock(self.record.id)
            acquired = competing_lock.acquire(blocking=False)
            if acquired:
                competing_lock.release()
            self.assertFalse(acquired)
            return temporal

        with (
            responses.RequestsMock() as http,
            patch("posthog.tasks.proxy.async_connect", side_effect=connect_while_deleting),
            patch(
                "posthog.tasks.proxy.reconcile_proxy.apply_async",
                side_effect=lambda args, kwargs, countdown: reconcile_proxy.run(*args, **kwargs),
            ),
        ):
            reconcile_managed_proxies.run()
            self.assertEqual(len(http.calls), 0)

        self.assertEqual(
            temporal.started,
            {
                f"proxy-delete-{self.record.id}": (
                    "delete-proxy",
                    DeleteManagedProxyInputs(
                        organization_id=self.organization.id,
                        proxy_record_id=self.record.id,
                        domain=self.record.domain,
                        target_cname=self.record.target_cname,
                        root_redirect_url=self.record.root_redirect_url,
                    ),
                )
            },
        )

    def test_sweep_recovers_failed_activation_enqueue_without_interrupting_commit_hooks(self) -> None:
        subsequent_hooks = []
        failed_records: list[str] = []

        def record_publish_failure(error: Exception, properties: dict[str, str]) -> None:
            failed_records.append(properties["proxy_record_id"])

        with (
            patch("posthog.tasks.proxy.reconcile_proxy.delay", side_effect=ConnectionError("broker unavailable")),
            patch("posthog.tasks.proxy.capture_exception", new=record_publish_failure),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.is_active = False
                self.organization.save(update_fields=["is_active"])
                transaction.on_commit(lambda: subsequent_hooks.append("completed"))
        self.assertEqual(subsequent_hooks, ["completed"])
        self.assertEqual(failed_records, [str(self.record.id)])
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=True)
            with patch(
                "posthog.tasks.proxy.reconcile_proxy.apply_async",
                side_effect=lambda args, kwargs, countdown: reconcile_proxy.run(*args, **kwargs),
            ):
                reconcile_managed_proxies.run()
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE", "DELETE"])


@override_settings(
    CLOUDFLARE_PROXY_BASE_CNAME="proxy.example.com",
    CLOUDFLARE_ZONE_ID="test-zone",
    CLOUDFLARE_API_TOKEN="test-token",
    CLOUDFLARE_PROXY_KV_NAMESPACE_ID="test-kv",
    CLOUDFLARE_ACCOUNT_ID="test-account",
)
class TestCloudflareProxyActivities(CloudflareProxyTestMixin, TransactionTestCase):
    async def test_recovery_waits_for_the_cloudflare_certificate(self) -> None:
        await ProxyRecord.objects.filter(pk=self.record.pk).aupdate(
            status=ProxyRecord.Status.ISSUING, needs_activation_recovery=True, cloudflare_deprovisioned=True
        )
        inputs = CreateCloudflareProxyInputs(
            organization_id=self.organization.pk, proxy_record_id=self.record.pk, domain=self.record.domain
        )
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            await create_cloudflare_custom_hostname(inputs)

        await self.record.arefresh_from_db()
        self.assertTrue(self.record.needs_activation_recovery)
        self.assertFalse(self.record.cloudflare_deprovisioned)

        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=True)
            await wait_for_cloudflare_certificate(inputs)

        await self.record.arefresh_from_db()
        self.assertFalse(self.record.needs_activation_recovery)

    async def test_status_update_recovers_from_a_closed_connection(self) -> None:
        @sync_to_async
        def close_driver_connection() -> None:
            connection.ensure_connection()
            assert connection.connection is not None
            connection.connection.close()
            connection.errors_occurred = True

        await close_driver_connection()
        await activity_update_proxy_record(
            UpdateProxyRecordInputs(
                organization_id=self.organization.pk,
                proxy_record_id=self.record.pk,
                status=ProxyRecord.Status.ERRORING,
            )
        )

        await self.record.arefresh_from_db()
        self.assertEqual(self.record.status, ProxyRecord.Status.ERRORING)

    async def test_creation_without_root_redirect_does_not_write_kv(self) -> None:
        await ProxyRecord.objects.filter(pk=self.record.pk).aupdate(root_redirect_url=None)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            await create_cloudflare_custom_hostname(
                CreateCloudflareProxyInputs(
                    organization_id=self.organization.pk,
                    proxy_record_id=self.record.pk,
                    domain=self.record.domain,
                )
            )
            self.assertEqual([call.request.method for call in http.calls], ["GET", "POST"])

    async def test_creation_does_not_provision_a_deactivated_organization(self) -> None:
        await Organization.objects.filter(pk=self.organization.pk).aupdate(is_active=False)
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            self._cloudflare(http, exists=False)
            with self.assertRaises(RecordDeletedException):
                await create_cloudflare_custom_hostname(
                    CreateCloudflareProxyInputs(
                        organization_id=self.organization.pk,
                        proxy_record_id=self.record.pk,
                        domain=self.record.domain,
                    )
                )
            self.assertEqual([call.request.method for call in http.calls], ["GET", "DELETE"])


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
