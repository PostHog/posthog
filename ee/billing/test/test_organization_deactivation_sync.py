import asyncio
import datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
from temporalio.common import WorkflowIDConflictPolicy

from posthog.models.organization import Organization, _start_billing_active_sync_workflow
from posthog.temporal.billing_active_sync.sync_organization_active_state import (
    RESYNC_SIGNAL,
    reconcile_organization_active_state,
    sync_organization_active_state,
)

from ee.billing.billing_manager import (
    DEACTIVATED_ORGANIZATIONS_SERVICE_ACTION,
    BillingManager,
    build_billing_system_token,
)
from ee.models.license import License, LicenseManager


def _create_license() -> License:
    return super(LicenseManager, cast(LicenseManager, License.objects)).create(
        key="key123::secret123",
        plan="enterprise",
        valid_until=datetime.datetime(2038, 1, 19, 3, 14, 7),
    )


class TestBuildBillingSystemToken(BaseTest):
    def test_token_is_org_less_and_action_scoped(self):
        license = _create_license()

        token = build_billing_system_token(license, DEACTIVATED_ORGANIZATIONS_SERVICE_ACTION)

        payload = jwt.decode(token, "secret123", algorithms=["HS256"], audience="posthog:license-key")
        assert payload["id"] == "key123"
        assert payload["service_action"] == "deactivated_organizations"
        assert "organization_id" not in payload
        assert "organization_name" not in payload


class TestDeactivatedOrganizationsClient(BaseTest):
    def setUp(self):
        super().setUp()
        self.license = _create_license()

    @patch(
        "ee.billing.billing_manager.http_session.post",
        return_value=MagicMock(
            status_code=200, json=MagicMock(return_value={"changed": 1, "already_set": 0, "not_found": []})
        ),
    )
    def test_set_organizations_deactivated_posts_the_batch(self, post_mock):
        result = BillingManager(self.license).set_organizations_deactivated(["org-1"], deactivated=True)

        assert result == {"changed": 1, "already_set": 0, "not_found": []}
        (url,) = post_mock.call_args.args
        assert url == "https://billing.posthog.com/api/internal/deactivated-organizations"
        assert post_mock.call_args.kwargs["json"] == {"organization_ids": ["org-1"], "deactivated": True}
        token = post_mock.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        payload = jwt.decode(token, "secret123", algorithms=["HS256"], audience="posthog:license-key")
        assert payload["service_action"] == "deactivated_organizations"
        assert "organization_id" not in payload

    @patch(
        "ee.billing.billing_manager.http_session.get",
        return_value=MagicMock(
            status_code=200, json=MagicMock(return_value={"deactivated_organization_ids": ["org-9"]})
        ),
    )
    def test_get_deactivated_organizations_returns_the_ids(self, get_mock):
        result = BillingManager(self.license).get_deactivated_organizations()

        assert result == ["org-9"]
        (url,) = get_mock.call_args.args
        assert url == "https://billing.posthog.com/api/internal/deactivated-organizations"

    @patch(
        "ee.billing.billing_manager.http_session.post",
        return_value=MagicMock(status_code=404, json=MagicMock(return_value={"detail": "not found"})),
    )
    def test_set_organizations_deactivated_raises_on_404(self, post_mock):
        with self.assertRaises(Exception):
            BillingManager(self.license).set_organizations_deactivated(["org-1"], deactivated=True)


class TestSyncActiveStateReceiver(BaseTest):
    def setUp(self):
        super().setUp()
        is_cloud_patcher = patch("posthog.models.organization.is_cloud", return_value=True)
        self.is_cloud_mock = is_cloud_patcher.start()
        self.addCleanup(is_cloud_patcher.stop)

    @patch("posthog.models.organization._start_billing_active_sync_workflow")
    def test_dispatches_on_is_active_flip(self, dispatch_mock):
        with self.captureOnCommitCallbacks(execute=True):
            self.organization.is_active = False
            self.organization.save(update_fields=["is_active"])

        dispatch_mock.assert_called_once_with(str(self.organization.pk))

    @patch("posthog.models.organization._start_billing_active_sync_workflow")
    def test_does_not_dispatch_on_unrelated_save(self, dispatch_mock):
        with self.captureOnCommitCallbacks(execute=True):
            self.organization.name = "renamed"
            self.organization.save(update_fields=["name"])

        dispatch_mock.assert_not_called()

    @patch("posthog.models.organization._start_billing_active_sync_workflow")
    def test_does_not_dispatch_on_create(self, dispatch_mock):
        with self.captureOnCommitCallbacks(execute=True):
            Organization.objects.create(name="fresh org")

        dispatch_mock.assert_not_called()

    @patch("posthog.models.organization._start_billing_active_sync_workflow")
    def test_does_not_dispatch_outside_cloud(self, dispatch_mock):
        self.is_cloud_mock.return_value = False

        with self.captureOnCommitCallbacks(execute=True):
            self.organization.is_active = False
            self.organization.save(update_fields=["is_active"])

        dispatch_mock.assert_not_called()


class TestStartBillingActiveSyncWorkflow(BaseTest):
    @patch("posthog.temporal.common.client.async_connect")
    def test_signals_a_running_sync_instead_of_replacing_it(self, connect_mock):
        client = MagicMock()
        client.start_workflow = AsyncMock()
        connect_mock.side_effect = AsyncMock(return_value=client)

        _start_billing_active_sync_workflow(str(self.organization.pk))

        kwargs = client.start_workflow.call_args.kwargs
        assert kwargs["id"] == f"billing-org-active-sync-{self.organization.pk}"
        assert kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.USE_EXISTING
        assert kwargs["start_signal"] == RESYNC_SIGNAL
        assert "id_reuse_policy" not in kwargs

    @patch("posthog.models.organization.BILLING_ACTIVE_SYNC_DISPATCH_TIMEOUT_SECONDS", 0.01)
    @patch("posthog.models.organization.logger")
    @patch("posthog.temporal.common.client.async_connect")
    def test_gives_up_when_temporal_does_not_answer(self, connect_mock, logger_mock):
        async def _hang():
            await asyncio.sleep(60)

        connect_mock.side_effect = _hang

        _start_billing_active_sync_workflow(str(self.organization.pk))

        logger_mock.warning.assert_called_once()
        assert logger_mock.warning.call_args.args == ("billing_active_state_sync_dispatch_failed",)


class TestSyncTasks(BaseTest):
    def setUp(self):
        super().setUp()
        self.license = _create_license()

    def _run_with_cloud(self, func, *args):
        with (
            patch("posthog.cloud_utils.is_cloud", return_value=True),
            patch("posthog.cloud_utils.get_cached_instance_license", return_value=self.license),
        ):
            func(*args)

    @patch("ee.billing.billing_manager.BillingManager.set_organizations_deactivated")
    def test_sync_task_pushes_the_inverse_of_is_active(self, set_mock):
        self.organization.is_active = False
        self.organization.save(update_fields=["is_active"])

        self._run_with_cloud(sync_organization_active_state, str(self.organization.pk))

        set_mock.assert_called_once_with([str(self.organization.pk)], deactivated=True)

    @patch("ee.billing.billing_manager.BillingManager.set_organizations_deactivated")
    def test_sync_task_treats_null_is_active_as_active(self, set_mock):
        self.organization.is_active = None
        self.organization.save(update_fields=["is_active"])

        self._run_with_cloud(sync_organization_active_state, str(self.organization.pk))

        set_mock.assert_called_once_with([str(self.organization.pk)], deactivated=False)

    @patch("ee.billing.billing_manager.BillingManager.set_organizations_deactivated")
    def test_sync_task_does_nothing_outside_cloud(self, set_mock):
        with patch("posthog.cloud_utils.is_cloud", return_value=False):
            sync_organization_active_state(str(self.organization.pk))

        set_mock.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.set_organizations_deactivated")
    @patch("ee.billing.billing_manager.BillingManager.get_deactivated_organizations")
    def test_reconciliation_pushes_deltas_in_both_directions(self, get_mock, set_mock):
        inactive_org = Organization.objects.create(name="blocked org", is_active=False)
        stale_org = Organization.objects.create(name="unblocked org", is_active=True)
        # billing still flags the unblocked org, misses the blocked one, and lists an id
        # this instance does not know (not ours to flip back).
        get_mock.return_value = [str(stale_org.pk), "01900000-0000-0000-0000-000000000000"]

        self._run_with_cloud(reconcile_organization_active_state)

        set_mock.assert_any_call([str(inactive_org.pk)], deactivated=True)
        set_mock.assert_any_call([str(stale_org.pk)], deactivated=False)
        assert set_mock.call_count == 2

    @patch("ee.billing.billing_manager.BillingManager.set_organizations_deactivated")
    @patch("ee.billing.billing_manager.BillingManager.get_deactivated_organizations")
    def test_reconciliation_reactivates_null_is_active_orgs(self, get_mock, set_mock):
        null_org = Organization.objects.create(name="null org", is_active=None)
        get_mock.return_value = [str(null_org.pk)]

        self._run_with_cloud(reconcile_organization_active_state)

        set_mock.assert_called_once_with([str(null_org.pk)], deactivated=False)

    @patch("ee.billing.billing_manager.BillingManager.set_organizations_deactivated")
    @patch("ee.billing.billing_manager.BillingManager.get_deactivated_organizations")
    def test_reconciliation_is_quiet_when_aligned(self, get_mock, set_mock):
        inactive_org = Organization.objects.create(name="blocked org", is_active=False)
        get_mock.return_value = [str(inactive_org.pk)]

        self._run_with_cloud(reconcile_organization_active_state)

        set_mock.assert_not_called()
