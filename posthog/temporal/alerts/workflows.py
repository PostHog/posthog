import json
import asyncio
import datetime as dt
from uuid import UUID

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.schema import AlertState

from posthog.slo.context import JsonValue
from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.alerts.activities import (
    cleanup_alert_checks,
    enqueue_alert_checks,
    evaluate_alert,
    notify_alert,
    prepare_alert,
    retrieve_due_alerts,
    run_investigation_safety_net,
)
from posthog.temporal.alerts.retry_policy import ALERT_NOTIFY_RETRY_POLICY, ALERT_PREPARE_RETRY_POLICY, alert_timeouts
from posthog.temporal.alerts.types import (
    AlertEvaluationDispatcherInputs,
    AlertInfo,
    CheckAlertWorkflowInputs,
    EnqueueAlertChecksActivityInputs,
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

        await temporalio.workflow.execute_activity(
            enqueue_alert_checks,
            EnqueueAlertChecksActivityInputs(alerts=alerts),
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=5),
                maximum_interval=dt.timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )


MAX_CONCURRENT_ALERT_CHECKS = 10


@temporalio.workflow.defn(name="alert-evaluation-dispatcher")
class AlertEvaluationDispatcherWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._pending_by_organization: dict[str, list[CheckAlertWorkflowInputs]] = {}
        self._pending_or_in_flight_alert_ids: set[str] = set()
        self._in_flight_alert_ids: set[str] = set()
        self._organization_cursor = 0

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.signal
    def enqueue_alerts(self, alerts: list[AlertInfo]) -> None:
        for alert in alerts:
            if alert.alert_id in self._pending_or_in_flight_alert_ids:
                continue

            slo_properties: dict[str, JsonValue] = {
                "alert_type": "insight",
                "calculation_interval": alert.calculation_interval,
                "insight_id": alert.insight_id,
            }
            inputs = CheckAlertWorkflowInputs(
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
            )
            self._pending_by_organization.setdefault(alert.organization_id, []).append(inputs)
            self._pending_or_in_flight_alert_ids.add(alert.alert_id)

    @temporalio.workflow.run
    async def run(self, dispatcher_inputs: AlertEvaluationDispatcherInputs | None = None) -> None:
        if dispatcher_inputs:
            self._pending_by_organization = dispatcher_inputs.pending_by_organization or {}
            self._pending_or_in_flight_alert_ids = set(dispatcher_inputs.pending_alert_ids or [])
            self._organization_cursor = dispatcher_inputs.organization_cursor

        while True:
            await temporalio.workflow.wait_condition(
                lambda: self._can_dispatch() or temporalio.workflow.info().is_continue_as_new_suggested()
            )
            if temporalio.workflow.info().is_continue_as_new_suggested():
                await temporalio.workflow.wait_condition(lambda: not self._in_flight_alert_ids)
                await temporalio.workflow.wait_condition(temporalio.workflow.all_handlers_finished)
                temporalio.workflow.continue_as_new(
                    AlertEvaluationDispatcherInputs(
                        pending_by_organization=self._pending_by_organization,
                        pending_alert_ids=sorted(self._pending_or_in_flight_alert_ids),
                        organization_cursor=self._organization_cursor,
                    )
                )

            while self._can_dispatch():
                inputs = self._next_alert()
                if inputs is None:
                    break

                self._in_flight_alert_ids.add(inputs.alert_id)
                try:
                    handle = await temporalio.workflow.start_child_workflow(
                        CheckAlertWorkflow.run,
                        inputs,
                        id=f"check-alert-{inputs.alert_id}",
                        parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                        execution_timeout=alert_timeouts(inputs.calculation_interval).workflow_execution,
                    )
                except WorkflowAlreadyStartedError:
                    temporalio.workflow.logger.info("check_alert.already_running", extra={"alert_id": inputs.alert_id})
                    self._complete_alert_check(inputs.alert_id)
                    continue
                asyncio.create_task(self._wait_for_alert_check(inputs.alert_id, handle))

    def _can_dispatch(self) -> bool:
        return bool(self._pending_by_organization) and len(self._in_flight_alert_ids) < MAX_CONCURRENT_ALERT_CHECKS

    def _next_alert(self) -> CheckAlertWorkflowInputs | None:
        organization_ids = list(self._pending_by_organization)
        if not organization_ids:
            return None

        organization_id = organization_ids[self._organization_cursor % len(organization_ids)]
        self._organization_cursor = (self._organization_cursor + 1) % len(organization_ids)
        inputs = self._pending_by_organization[organization_id].pop(0)
        if not self._pending_by_organization[organization_id]:
            del self._pending_by_organization[organization_id]
        return inputs

    async def _wait_for_alert_check(self, alert_id: str, handle: temporalio.workflow.ChildWorkflowHandle) -> None:
        try:
            await handle
        except WorkflowAlreadyStartedError:
            temporalio.workflow.logger.info("check_alert.already_running", extra={"alert_id": alert_id})
        except Exception:
            temporalio.workflow.logger.exception("check_alert.child_workflow_error", extra={"alert_id": alert_id})
        finally:
            self._complete_alert_check(alert_id)

    def _complete_alert_check(self, alert_id: str) -> None:
        self._in_flight_alert_ids.discard(alert_id)
        self._pending_or_in_flight_alert_ids.discard(alert_id)


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
                start_to_close_timeout=dt.timedelta(minutes=2),
                schedule_to_close_timeout=timeouts.activity_schedule_to_close,
                retry_policy=ALERT_PREPARE_RETRY_POLICY,
            )

            if prepare_result.action != PrepareAction.EVALUATE:
                skip_reason = prepare_result.reason
                return

            # Phase 2 — evaluate: CH query + state machine + persist AlertCheck
            evaluation = await temporalio.workflow.execute_activity(
                evaluate_alert,
                EvaluateAlertActivityInputs(alert_id=inputs.alert_id),
                start_to_close_timeout=timeouts.evaluate_start_to_close,
                schedule_to_close_timeout=timeouts.activity_schedule_to_close,
                heartbeat_timeout=timeouts.heartbeat_timeout,
                retry_policy=timeouts.evaluate_retry_policy,
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
