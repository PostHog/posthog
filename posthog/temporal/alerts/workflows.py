import json
import asyncio
import datetime as dt

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.alerts.activities import (
    enumerate_due_alerts_activity,
    evaluate_alert_activity,
    notify_alert_activity,
    prepare_alert_activity,
)
from posthog.temporal.alerts.retry_policy import ALERT_EVALUATE_RETRY_POLICY, ALERT_NOTIFY_RETRY_POLICY
from posthog.temporal.alerts.types import (
    CheckAlertWorkflowInputs,
    EnumerateDueAlertsActivityInputs,
    EvaluateAlertActivityInputs,
    NotifyAlertActivityInputs,
    PrepareAlertActivityInputs,
    ScheduleAllAlertChecksWorkflowInputs,
)
from posthog.temporal.common.base import PostHogWorkflow


@temporalio.workflow.defn(name="schedule-all-alert-checks")
class ScheduleAllAlertChecksWorkflow(PostHogWorkflow):
    """Coordinator workflow — runs every 2 minutes via a Temporal Schedule.

    Mirrors ScheduleAllSubscriptionsWorkflow at
    posthog/temporal/subscriptions/workflows.py:67. No SLO instrumentation
    — coordinator is pure dispatch and shouldn't show up in alert SLO
    metrics.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ScheduleAllAlertChecksWorkflowInputs:
        if not inputs:
            return ScheduleAllAlertChecksWorkflowInputs()
        loaded = json.loads(inputs[0])
        return ScheduleAllAlertChecksWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ScheduleAllAlertChecksWorkflowInputs) -> None:
        alerts = await temporalio.workflow.execute_activity(
            enumerate_due_alerts_activity,
            EnumerateDueAlertsActivityInputs(),
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )

        # Fan-out child workflows — one per alert. Deterministic ID prevents
        # duplicate checks when schedule runs overlap; Temporal guarantees no
        # two open workflows can share the same ID, so a still-running child
        # rejects the duplicate start.
        tasks = []
        for alert in alerts:
            task = temporalio.workflow.execute_child_workflow(
                CheckAlertWorkflow.run,
                CheckAlertWorkflowInputs(
                    alert_id=alert.alert_id,
                    team_id=alert.team_id,
                    distinct_id=alert.distinct_id,
                    calculation_interval=alert.calculation_interval,
                    insight_id=alert.insight_id,
                    slo=SloConfig(
                        operation=SloOperation.ALERT_CHECK,
                        area=SloArea.ANALYTIC_PLATFORM,
                        team_id=alert.team_id,
                        resource_id=alert.alert_id,
                        distinct_id=alert.distinct_id,
                        start_properties={
                            "calculation_interval": alert.calculation_interval,
                            "insight_id": alert.insight_id,
                        },
                    ),
                ),
                id=f"check-alert-{alert.alert_id}",
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(minutes=15),
            )
            tasks.append(task)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            failed_ids = []
            for alert, result in zip(alerts, results):
                if isinstance(result, BaseException):
                    if isinstance(result, WorkflowAlreadyStartedError):
                        # Previous schedule run's child still processing this
                        # alert — not a failure, just skip it.
                        temporalio.workflow.logger.info(
                            "check_alert.already_running",
                            extra={"alert_id": alert.alert_id},
                        )
                    else:
                        failed_ids.append(alert.alert_id)
                        temporalio.workflow.logger.warning(
                            "check_alert.child_workflow_error",
                            extra={"alert_id": alert.alert_id, "error": str(result)},
                        )

            if failed_ids:
                raise ApplicationError(
                    f"Alert checks failed for IDs: {failed_ids}",
                    non_retryable=True,
                )


@temporalio.workflow.defn(name="check-alert")
class CheckAlertWorkflow(PostHogWorkflow):
    """One alert check, three phases.

    SLO instrumented automatically by slo_interceptor via the `slo` field on
    inputs. Mirrors ProcessSubscriptionWorkflow at
    posthog/temporal/subscriptions/workflows.py:147.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CheckAlertWorkflowInputs:
        loaded = json.loads(inputs[0])
        return CheckAlertWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: CheckAlertWorkflowInputs) -> None:
        new_state: str | None = None
        skip_reason: str | None = None
        caught_error: BaseException | None = None

        try:
            # Phase 1 — prepare: load alert, validate config, check should-skip
            prepare_result = await temporalio.workflow.execute_activity(
                prepare_alert_activity,
                PrepareAlertActivityInputs(alert_id=inputs.alert_id),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
            )

            if prepare_result.action != "evaluate":
                skip_reason = prepare_result.reason
                return  # exit cleanly; finally block still runs

            # Phase 2 — evaluate: CH query + state machine + persist AlertCheck
            evaluation = await temporalio.workflow.execute_activity(
                evaluate_alert_activity,
                EvaluateAlertActivityInputs(alert_id=inputs.alert_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=ALERT_EVALUATE_RETRY_POLICY,
            )
            new_state = evaluation.new_state

            # Phase 3 — notify (optional)
            if evaluation.should_notify:
                await temporalio.workflow.execute_activity(
                    notify_alert_activity,
                    NotifyAlertActivityInputs(
                        alert_id=inputs.alert_id,
                        alert_check_id=evaluation.alert_check_id,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=ALERT_NOTIFY_RETRY_POLICY,
                )

        except Exception as e:
            # Workflow-level failure: the SLO interceptor populates
            # error_type / error_message / error_trace when we re-raise.
            caught_error = e

        finally:
            # Enrich SLO completion context with alert-specific details.
            # Mirrors ProcessSubscriptionWorkflow at
            # posthog/temporal/subscriptions/workflows.py:262-271.
            if inputs.slo:
                completion_props: dict = {}
                if new_state is not None:
                    completion_props["alert_state"] = new_state
                if skip_reason is not None:
                    completion_props["skip_reason"] = skip_reason
                if completion_props:
                    inputs.slo.completion_properties.update(completion_props)

        # Re-raise after cleanup completes. Same Temporal SDK quirk as
        # ProcessSubscriptionWorkflow — re-raising inside `except` blocks
        # new activity scheduling in `finally`.
        if caught_error:
            raise caught_error
