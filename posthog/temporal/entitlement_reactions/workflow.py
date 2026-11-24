import asyncio
from datetime import timedelta

from temporalio import common, workflow
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.base import PostHogWorkflow
    from posthog.temporal.entitlement_reactions.activities import (
        execute_entitlement_reactor_activity,
        list_behind_entitlement_reactors_activity,
    )
    from posthog.temporal.entitlement_reactions.contracts import (
        EntitlementReactionsInputs,
        EntitlementReactionsResult,
        ExecuteEntitlementReactorInputs,
    )

RESYNC_SIGNAL = "resync"
MAX_ROUNDS_PER_RUN = 20


@workflow.defn(name="entitlement-reactions")
class EntitlementReactionsWorkflow(PostHogWorkflow):
    inputs_cls = EntitlementReactionsInputs

    def __init__(self) -> None:
        self._resync_requested = False

    @workflow.signal(name=RESYNC_SIGNAL)
    def resync(self) -> None:
        self._resync_requested = True

    async def _execute_reactor(self, inputs: ExecuteEntitlementReactorInputs) -> str | None:
        try:
            await workflow.execute_activity(
                execute_entitlement_reactor_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=2),
                schedule_to_close_timeout=timedelta(minutes=15),
                retry_policy=common.RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    maximum_interval=timedelta(minutes=2),
                    maximum_attempts=5,
                ),
            )
        except ActivityError:
            workflow.logger.warning("Entitlement reactor exhausted retries", extra={"reactor_key": inputs.reactor_key})
            workflow.metric_meter().create_counter("entitlement_reactor_failures").add(1)
            return inputs.reactor_key
        return None

    @workflow.run
    async def run(self, inputs: EntitlementReactionsInputs) -> EntitlementReactionsResult:
        rounds = 0
        while True:
            self._resync_requested = False
            keys = await workflow.execute_activity(
                list_behind_entitlement_reactors_activity,
                inputs,
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(minutes=3),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            failures = await asyncio.gather(
                *(
                    self._execute_reactor(
                        ExecuteEntitlementReactorInputs(organization_id=inputs.organization_id, reactor_key=key)
                    )
                    for key in keys
                )
            )
            rounds += 1
            if not self._resync_requested:
                return EntitlementReactionsResult(failed_reactor_keys=[key for key in failures if key is not None])
            if rounds >= MAX_ROUNDS_PER_RUN or workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(inputs)
