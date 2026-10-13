import json
import datetime as dt
from uuid import UUID

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.schema import AlertState

from posthog.slo.context import JsonValue
from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.alerts.activities import (
    admit_alert_evaluations,
    cleanup_alert_checks,
    evaluate_alert,
    notify_alert,
    prepare_alert,
    record_failed_evaluation,
    release_alert_evaluation_slots,
    retrieve_due_alerts,
    run_investigation_safety_net,
)
from posthog.temporal.alerts.retry_policy import (
    ALERT_NOTIFY_RETRY_POLICY,
    ALERT_PREPARE_RETRY_POLICY,
    AlertTimeouts,
    alert_timeouts,
)
from posthog.temporal.alerts.types import (
    AdmitEvaluationsInputs,
    AlertInfo,
    CheckAlertWorkflowInputs,
    EvaluateAlertActivityInputs,
    NotifyAlertActivityInputs,
    PrepareAction,
    PrepareAlertActivityInputs,
    RecordFailedEvaluationActivityInputs,
    ReleaseEvaluationSlotsInputs,
    ScheduleDueAlertChecksWorkflowInputs,
    SkipReason,
    UnstartedChecks,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import MAX_ERROR_MESSAGE_CHARS, truncate_for_temporal_payload, unwrap_temporal_cause

with temporalio.workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.temporal.ai.anomaly_investigation import AnomalyInvestigationWorkflowInputs


# Runs started before the deploy replay the fan-out; drop the gate once no such run is left.
_PATCH_INFLIGHT_ADMISSION = "alerts-inflight-admission-2026-09"
_ADMISSION_POLL_INTERVAL = dt.timedelta(seconds=2)
# Under the one-minute schedule cadence, so the next run takes over what this one did not reach.
_ADMISSION_RUN_BUDGET = dt.timedelta(seconds=50)
_ADMISSION_ACTIVITY_RETRY_POLICY = temporalio.common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    maximum_attempts=5,
)


@temporalio.workflow.defn(name="schedule-due-alert-checks")
class ScheduleDueAlertChecksWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ScheduleDueAlertChecksWorkflowInputs:
        if not inputs:
            return ScheduleDueAlertChecksWorkflowInputs()

        loaded = json.loads(inputs[0])
        return ScheduleDueAlertChecksWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ScheduleDueAlertChecksWorkflowInputs | None = None) -> None:
        if inputs is None:
            inputs = ScheduleDueAlertChecksWorkflowInputs()

        if not temporalio.workflow.patched(_PATCH_INFLIGHT_ADMISSION):
            unstarted = await self._start_checks(await self._retrieve_due_alerts(inputs))
            self._raise_for_failed_starts(unstarted.failed_ids)
            return

        failed_ids: list[str] = []
        pending: list[AlertInfo] = []
        deadline = temporalio.workflow.now() + _ADMISSION_RUN_BUDGET
        while temporalio.workflow.now() < deadline:
            alerts = await self._retrieve_due_alerts(inputs)
            pending = list(alerts)
            while pending and temporalio.workflow.now() < deadline:
                expires_at = (temporalio.workflow.now() + alert_timeouts(None).workflow_execution).timestamp()
                admitted = await temporalio.workflow.execute_activity(
                    admit_alert_evaluations,
                    AdmitEvaluationsInputs(alert_ids=[alert.alert_id for alert in pending], expires_at=expires_at),
                    start_to_close_timeout=dt.timedelta(seconds=30),
                    retry_policy=_ADMISSION_ACTIVITY_RETRY_POLICY,
                )
                if admitted.alert_ids:
                    admitted_ids = set(admitted.alert_ids)
                    batch = [alert for alert in pending if alert.alert_id in admitted_ids]
                    pending = [alert for alert in pending if alert.alert_id not in admitted_ids]
                    unstarted = await self._start_checks(batch)
                    failed_ids.extend(unstarted.failed_ids)
                    if unstarted.alert_ids:
                        await self._release_slots(unstarted.alert_ids, expires_at)
                if pending:
                    await temporalio.workflow.sleep(_ADMISSION_POLL_INTERVAL)
            # A short page means nothing else is due; a full page may hide more behind it.
            if pending or not alerts or len(alerts) < inputs.max_alerts_per_run:
                break

        if pending:
            temporalio.workflow.logger.info(
                "check_alert.admission_budget_exhausted",
                extra={"remaining": len(pending)},
            )
        self._raise_for_failed_starts(failed_ids)

    async def _release_slots(self, alert_ids: list[str], expires_at: float) -> None:
        """Give back reservations no child will use: the start failed, or the check was already running.

        Admission returned only ids written under this expiry, and a running check holds its slot
        under its own, so a release keyed on it cannot take that slot away.
        """
        await temporalio.workflow.execute_activity(
            release_alert_evaluation_slots,
            ReleaseEvaluationSlotsInputs(alert_ids=alert_ids, held_until=expires_at),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_ADMISSION_ACTIVITY_RETRY_POLICY,
        )

    async def _retrieve_due_alerts(self, inputs: ScheduleDueAlertChecksWorkflowInputs) -> list[AlertInfo]:
        return await temporalio.workflow.execute_activity(
            retrieve_due_alerts,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )

    @staticmethod
    def _raise_for_failed_starts(failed_ids: list[str]) -> None:
        if failed_ids:
            raise ApplicationError(
                f"Alert checks failed to start for IDs: {failed_ids}",
                non_retryable=True,
            )

    async def _start_checks(self, alerts: list[AlertInfo]) -> UnstartedChecks:
        """Start one child workflow per alert and return the ids that did not get a new check.

        Deterministic IDs prevent duplicate checks from retries or concurrent manual triggers. Wait
        only for Temporal to accept the start; the children run independently.
        """
        failed_ids: list[str] = []
        already_running_ids: list[str] = []
        for alert in alerts:
            slo_properties: dict[str, JsonValue] = {
                "alert_type": "insight",
                "calculation_interval": alert.calculation_interval,
                "insight_id": alert.insight_id,
            }
            try:
                await temporalio.workflow.start_child_workflow(
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
                            start_properties=slo_properties.copy(),
                            completion_properties=slo_properties.copy(),
                        ),
                    ),
                    id=f"check-alert-{alert.alert_id}",
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=alert_timeouts(alert.calculation_interval).workflow_execution,
                )
            except WorkflowAlreadyStartedError:
                already_running_ids.append(alert.alert_id)
                temporalio.workflow.logger.info(
                    "check_alert.already_running",
                    extra={"alert_id": alert.alert_id},
                )
            except Exception as error:
                failed_ids.append(alert.alert_id)
                temporalio.workflow.logger.warning(
                    "check_alert.start_failed",
                    extra={"alert_id": alert.alert_id, "error": str(error)},
                )
        return UnstartedChecks(failed_ids=failed_ids, already_running_ids=already_running_ids)


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
        timeouts = alert_timeouts(inputs.calculation_interval)

        try:
            # Phase 1 — prepare: load alert, validate config, check should-skip
            prepare_result = await temporalio.workflow.execute_activity(
                prepare_alert,
                PrepareAlertActivityInputs(alert_id=inputs.alert_id),
                start_to_close_timeout=timeouts.prepare_start_to_close,
                schedule_to_close_timeout=timeouts.activity_schedule_to_close,
                retry_policy=ALERT_PREPARE_RETRY_POLICY,
            )

            if prepare_result.action != PrepareAction.EVALUATE:
                skip_reason = prepare_result.reason
                return

            # Phase 2 — evaluate: CH query + state machine + persist AlertCheck
            # An AI detector calls a model, and only the AI worker holds the provider
            # credentials, so that check evaluates on the AI queue.
            evaluate_task_queue = (
                settings.MAX_AI_TASK_QUEUE
                if prepare_result.uses_llm_detector
                and temporalio.workflow.patched("alerts-evaluate-ai-detector-on-ai-queue")
                else None
            )
            try:
                evaluation = await temporalio.workflow.execute_activity(
                    evaluate_alert,
                    EvaluateAlertActivityInputs(
                        alert_id=inputs.alert_id,
                        calculation_interval=inputs.calculation_interval,
                        uses_llm_detector=prepare_result.uses_llm_detector,
                        team_id=inputs.team_id,
                    ),
                    task_queue=evaluate_task_queue,
                    start_to_close_timeout=timeouts.evaluate_start_to_close,
                    schedule_to_close_timeout=timeouts.activity_schedule_to_close,
                    heartbeat_timeout=timeouts.heartbeat_timeout,
                    retry_policy=timeouts.evaluate_retry_policy,
                )
            except Exception as evaluation_error:
                # Transient ClickHouse errors re-raise so the retry policy can get past a busy
                # cluster. Once those run out no AlertCheck exists and next_check_at is still in the
                # past, so record the failure to stop the sweep restarting the chain forever. Set
                # the state first so the SLO completion event still attributes this as errored.
                # (No workflow.patched guard needed: this only runs on the path that fails the
                # workflow, so no open execution has already replayed past it.)
                new_state = AlertState.ERRORED
                try:
                    await self._record_failed_evaluation(
                        inputs, timeouts, evaluation_error, prepare_result.evaluation_fingerprint
                    )
                except Exception:
                    # A failure while recording must not replace the original evaluation error: the
                    # bare raise below still re-raises evaluation_error, not this one.
                    temporalio.workflow.logger.warning(
                        "alerts.record_failed_evaluation_failed", extra={"alert_id": inputs.alert_id}
                    )
                raise
            if evaluation.alert_check_id is None:
                skip_reason = SkipReason.CHANGED_DURING_EVALUATION
                return
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
                    start_to_close_timeout=timeouts.notify_start_to_close,
                    schedule_to_close_timeout=timeouts.activity_schedule_to_close,
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

    async def _record_failed_evaluation(
        self,
        inputs: CheckAlertWorkflowInputs,
        timeouts: AlertTimeouts,
        evaluation_error: BaseException,
        evaluation_fingerprint: str | None = None,
    ) -> None:
        """Write the errored AlertCheck the failed evaluation never got to write, then notify."""
        # Unwrap Temporal's ActivityError plumbing to the underlying reason the owner sees in the
        # error email, and bound it so a large trace can't blow the payload limit or the DB row.
        cause = unwrap_temporal_cause(evaluation_error)
        message = cause.message if cause is not None else str(evaluation_error)
        message = truncate_for_temporal_payload(message, MAX_ERROR_MESSAGE_CHARS)
        # Temporal rebuilds a remote failure as a bare ApplicationError with the original class
        # name on `type`, which is all the activity needs to pick the owner-facing reason.
        error_type = cause.type if cause is not None else type(evaluation_error).__name__
        recorded = await temporalio.workflow.execute_activity(
            record_failed_evaluation,
            RecordFailedEvaluationActivityInputs(
                alert_id=inputs.alert_id,
                error_message=message,
                error_type=error_type,
                evaluation_fingerprint=evaluation_fingerprint,
                team_id=inputs.team_id,
            ),
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=ALERT_PREPARE_RETRY_POLICY,
        )
        if not recorded.should_notify or not recorded.alert_check_id:
            return

        await temporalio.workflow.execute_activity(
            notify_alert,
            NotifyAlertActivityInputs(
                alert_id=inputs.alert_id,
                alert_check_id=recorded.alert_check_id,
                breaches=None,
            ),
            start_to_close_timeout=timeouts.notify_start_to_close,
            retry_policy=ALERT_NOTIFY_RETRY_POLICY,
        )


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


@temporalio.workflow.defn(name="cleanup-alert-checks")
class CleanupAlertChecksWorkflow(PostHogWorkflow):
    """Purge old AlertCheck rows on a daily schedule."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self) -> None:
        await temporalio.workflow.execute_activity(
            cleanup_alert_checks,
            start_to_close_timeout=dt.timedelta(minutes=30),
            heartbeat_timeout=dt.timedelta(minutes=2),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )
