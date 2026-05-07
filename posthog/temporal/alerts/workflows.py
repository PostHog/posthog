import json
import asyncio
import datetime as dt
from uuid import UUID

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.schema import AlertState

from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.alerts.activities import (
    evaluate_alert,
    notify_alert,
    prepare_alert,
    retrieve_due_alerts,
    run_investigation_safety_net,
)
from posthog.temporal.alerts.retry_policy import (
    ALERT_EVALUATE_RETRY_POLICY,
    ALERT_NOTIFY_RETRY_POLICY,
    ALERT_PREPARE_RETRY_POLICY,
)
from posthog.temporal.alerts.types import (
    CheckAlertWorkflowInputs,
    EvaluateAlertActivityInputs,
    NotifyAlertActivityInputs,
    PrepareAction,
    PrepareAlertActivityInputs,
)
from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.temporal.ai.anomaly_investigation import AnomalyInvestigationWorkflowInputs


@temporalio.workflow.defn(name="schedule-due-alert-checks")
class ScheduleDueAlertChecksWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self) -> None:
        alerts = await temporalio.workflow.execute_activity(
            retrieve_due_alerts,
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
                        completion_properties={
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
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CheckAlertWorkflowInputs:
        loaded = json.loads(inputs[0])
        return CheckAlertWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: CheckAlertWorkflowInputs) -> None:
        new_state: AlertState | None = None
        skip_reason: str | None = None
        caught_error: BaseException | None = None

        try:
            # Phase 1 — prepare: load alert, validate config, check should-skip
            prepare_result = await temporalio.workflow.execute_activity(
                prepare_alert,
                PrepareAlertActivityInputs(alert_id=inputs.alert_id),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=ALERT_PREPARE_RETRY_POLICY,
            )

            if prepare_result.action != PrepareAction.EVALUATE:
                skip_reason = prepare_result.reason
                return

            # Phase 2 — evaluate: CH query + state machine + persist AlertCheck
            evaluation = await temporalio.workflow.execute_activity(
                evaluate_alert,
                EvaluateAlertActivityInputs(alert_id=inputs.alert_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=ALERT_EVALUATE_RETRY_POLICY,
            )
            new_state = evaluation.new_state

            # Phase 3 — notify (optional)
            # Skip the synchronous notify when the investigation agent is gating —
            # the AnomalyInvestigationWorkflow will dispatch (or suppress) after the
            # verdict, and the safety-net schedule force-fires if the workflow stalls.
            if evaluation.should_notify and not evaluation.should_gate_notification:
                await temporalio.workflow.execute_activity(
                    notify_alert,
                    NotifyAlertActivityInputs(
                        alert_id=inputs.alert_id,
                        alert_check_id=evaluation.alert_check_id,
                        breaches=evaluation.breaches,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=ALERT_NOTIFY_RETRY_POLICY,
                )

            # Phase 4 — kick off the anomaly investigation as an abandoned child
            # so it lives independently of this workflow's lifetime. Runs on the
            # AI task queue and uses a deterministic ID per AlertCheck so retries
            # of CheckAlertWorkflow don't double-start the investigation.
            if evaluation.should_start_investigation:
                await temporalio.workflow.start_child_workflow(
                    "anomaly-investigation",
                    AnomalyInvestigationWorkflowInputs(
                        team_id=inputs.team_id,
                        alert_id=UUID(inputs.alert_id),
                        alert_check_id=UUID(evaluation.alert_check_id),
                        user_id=evaluation.investigation_user_id,
                    ),
                    id=f"anomaly-investigation-{evaluation.alert_check_id}",
                    task_queue=settings.MAX_AI_TASK_QUEUE,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                )

        except Exception as e:
            caught_error = e

        finally:
            if inputs.slo:
                completion_props: dict = {}
                if new_state is not None:
                    completion_props["alert_state"] = new_state
                if skip_reason is not None:
                    completion_props["skip_reason"] = skip_reason

                if completion_props:
                    inputs.slo.completion_properties.update(completion_props)

        # Re-raise after cleanup completes. Same Temporal SDK quirk as ProcessSubscriptionWorkflow
        if caught_error:
            raise caught_error


@temporalio.workflow.defn(name="run-investigation-safety-net")
class RunInvestigationSafetyNetWorkflow(PostHogWorkflow):
    """Periodic sweep that force-dispatches notifications for stalled investigation checks.

    Runs as a Temporal schedule (see posthog/temporal/alerts/schedule.py). The actual
    DB scan + dispatch lives in `run_investigation_safety_net` so the workflow stays
    a thin shell.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self) -> None:
        await temporalio.workflow.execute_activity(
            run_investigation_safety_net,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(seconds=30),
                maximum_attempts=2,
            ),
        )
