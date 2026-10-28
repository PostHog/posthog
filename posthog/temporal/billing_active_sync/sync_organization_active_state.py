import json
from datetime import timedelta

import structlog
from temporalio import activity, common, workflow

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger()


@frozen
class SyncOrganizationActiveStateInputs:
    organization_id: str


@frozen
class ReconcileOrganizationActiveStateInputs:
    pass


def sync_organization_active_state(organization_id: str) -> None:
    """Mirror Organization.is_active into billing's deactivated flag (forecast exclusion).

    Reads the organization inside this function so every retry attempt sees the latest
    is_active value.
    """
    from posthog.cloud_utils import get_cached_instance_license, is_cloud
    from posthog.models import Organization

    from ee.billing.billing_manager import BillingManager

    if not is_cloud():
        return
    license = get_cached_instance_license()
    if license is None:
        return

    organization = Organization.objects.get(id=organization_id)
    # is_active is nullable; the rest of the app treats only an explicit False as deactivated.
    BillingManager(license, None).set_organizations_deactivated(
        [str(organization.id)], deactivated=organization.is_active is False
    )


def reconcile_organization_active_state() -> None:
    """Nightly sweep: realign billing's deactivated flags with Organization.is_active.

    The post_save signal is the real-time path; this catches missed flips (worker loss,
    writes that skip signals). Organization.is_active is authoritative in both directions,
    so a flag set only in billing for an org that is active here is removed.
    """
    from posthog.cloud_utils import get_cached_instance_license, is_cloud
    from posthog.models import Organization

    from ee.billing.billing_manager import BillingManager

    if not is_cloud():
        return
    license = get_cached_instance_license()
    if license is None:
        return

    manager = BillingManager(license, None)
    billing_deactivated = set(manager.get_deactivated_organizations())
    # Nullable is_active: only an explicit False is deactivated, so null lands on the reactivation side.
    inactive = {str(pk) for pk in Organization.objects.filter(is_active=False).values_list("id", flat=True)}

    to_deactivate = sorted(inactive - billing_deactivated)
    # An id this instance does not know (e.g. a deleted org) is not ours to flip back.
    to_reactivate = sorted(
        str(pk)
        for pk in Organization.objects.filter(id__in=billing_deactivated)
        .exclude(is_active=False)
        .values_list("id", flat=True)
    )
    # Billing caps a batch at 1000 organization ids.
    batch_size = 500
    for batch_start in range(0, len(to_deactivate), batch_size):
        manager.set_organizations_deactivated(to_deactivate[batch_start : batch_start + batch_size], deactivated=True)
    for batch_start in range(0, len(to_reactivate), batch_size):
        manager.set_organizations_deactivated(to_reactivate[batch_start : batch_start + batch_size], deactivated=False)


@activity.defn(name="sync-organization-active-state")
async def sync_organization_active_state_activity(inputs: SyncOrganizationActiveStateInputs) -> None:
    async with Heartbeater():
        try:
            await database_sync_to_async_pool(sync_organization_active_state)(inputs.organization_id)
        except Exception as e:
            capture_exception(e)
            # Raise exception without large context to avoid "Failure exceeds size limit"
            raise Exception(f"Organization active state sync failed: {type(e).__name__}: {str(e)[:200]}")


@activity.defn(name="reconcile-organization-active-state")
async def reconcile_organization_active_state_activity(_inputs: ReconcileOrganizationActiveStateInputs) -> None:
    async with Heartbeater():
        try:
            await database_sync_to_async_pool(reconcile_organization_active_state)()
        except Exception as e:
            capture_exception(e)
            # Raise exception without large context to avoid "Failure exceeds size limit"
            raise Exception(f"Organization active state reconciliation failed: {type(e).__name__}: {str(e)[:200]}")


RESYNC_SIGNAL = "resync"


@workflow.defn(name="sync-organization-active-state-to-billing")
class SyncOrganizationActiveStateWorkflow(PostHogWorkflow):
    """One run per organization; a flip during a run signals it to sync again, so no stale POST lands last."""

    def __init__(self) -> None:
        self._resync_requested = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyncOrganizationActiveStateInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SyncOrganizationActiveStateInputs(**loaded)

    @workflow.signal(name=RESYNC_SIGNAL)
    def resync(self) -> None:
        self._resync_requested = True

    @workflow.run
    async def run(self, inputs: SyncOrganizationActiveStateInputs) -> None:
        while True:
            self._resync_requested = False
            await workflow.execute_activity(
                sync_organization_active_state_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=common.RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(minutes=5),
                    maximum_attempts=6,
                ),
                heartbeat_timeout=timedelta(minutes=1),
            )
            if not self._resync_requested:
                return


@workflow.defn(name="reconcile-organization-active-state-to-billing")
class ReconcileOrganizationActiveStateWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ReconcileOrganizationActiveStateInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return ReconcileOrganizationActiveStateInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ReconcileOrganizationActiveStateInputs) -> None:
        await workflow.execute_activity(
            reconcile_organization_active_state_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=common.RetryPolicy(
                initial_interval=timedelta(minutes=1),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(minutes=10),
                maximum_attempts=4,
            ),
            heartbeat_timeout=timedelta(minutes=2),
        )
