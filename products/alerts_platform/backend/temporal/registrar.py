"""The registrar: records what each source's feed saw into the occurrence registry, on its own queue.

It runs apart from evaluation, so a feed read that is slow, or that fails, delays only the
identities it would record. Appearance checks read the registry and never wait on a feed.
"""

import asyncio
import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts_platform.backend.facade.contracts import SourceKind

REGISTRAR_WORKFLOW_NAME = "alerts-platform-register-occurrences"
# How long one run keeps reading one project's feed. A registry far behind, such as one seeding,
# catches up over several runs. A feed read can take a full read budget past this.
REGISTER_BUDGET = dt.timedelta(seconds=60)
REGISTER_START_TO_CLOSE = dt.timedelta(minutes=2)
# Projects one run reads at once, so a run with many projects does not take every worker slot.
MAX_CONCURRENT_REGISTRATIONS = 8


@frozen
class RegistrarInputs:
    pass


@frozen
class RegistrarTarget:
    source: SourceKind
    team_id: int


@activity.defn
@close_db_connections
def alerts_platform_registrar_targets_activity() -> list[RegistrarTarget]:
    # Imported in the body, because the workflow below makes this module load inside Temporal's
    # sandbox, which refuses a Django model import.
    from products.alerts_platform.backend.logic import occurrences  # noqa: PLC0415

    return [RegistrarTarget(source=source, team_id=team_id) for source, team_id in occurrences.registrar_targets()]


@activity.defn
@close_db_connections
def alerts_platform_register_occurrences_activity(target: RegistrarTarget) -> None:
    """Sync, so the thread this blocks is a slot the worker's activity executor accounts for."""
    from products.alerts_platform.backend.logic import occurrences  # noqa: PLC0415

    occurrences.store_for(target.source).catch_up(
        team_id=target.team_id, now=dt.datetime.now(dt.UTC), budget=REGISTER_BUDGET
    )


@workflow.defn(name=REGISTRAR_WORKFLOW_NAME)
class AlertsPlatformRegisterOccurrencesWorkflow(PostHogWorkflow):
    """Brings each project's registry up to what its sources' feeds have finished."""

    inputs_cls = RegistrarInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: RegistrarInputs) -> int:
        targets = await workflow.execute_activity(
            alerts_platform_registrar_targets_activity,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        slots = asyncio.Semaphore(MAX_CONCURRENT_REGISTRATIONS)

        async def register(target: RegistrarTarget) -> bool:
            async with slots:
                try:
                    # One attempt. A failed read shortens the cursor's span, so the next run asks for less.
                    await workflow.execute_activity(
                        alerts_platform_register_occurrences_activity,
                        target,
                        start_to_close_timeout=REGISTER_START_TO_CLOSE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                except Exception:
                    workflow.logger.warning(
                        "Registering occurrences failed", extra={"source": target.source, "team_id": target.team_id}
                    )
                    return False
                return True

        registered = await asyncio.gather(*(register(target) for target in targets))
        return sum(registered)


REGISTRAR_WORKFLOWS = [AlertsPlatformRegisterOccurrencesWorkflow]
REGISTRAR_ACTIVITIES = [alerts_platform_registrar_targets_activity, alerts_platform_register_occurrences_activity]
