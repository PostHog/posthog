"""Activities for evaluation reports workflow."""

import datetime as dt

import temporalio.activity
from structlog import get_logger

from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.eval_reports.types import (
    DeliverReportInput,
    FetchDueEvalReportsOutput,
    PrepareReportContextInput,
    PrepareReportContextOutput,
    RunEvalReportAgentInput,
    RunEvalReportAgentOutput,
    ScheduleAllEvalReportsWorkflowInputs,
    StoreReportRunInput,
    StoreReportRunOutput,
    UpdateNextDeliveryDateInput,
)

logger = get_logger(__name__)


@temporalio.activity.defn
async def fetch_due_eval_reports_activity(
    inputs: ScheduleAllEvalReportsWorkflowInputs,
) -> FetchDueEvalReportsOutput:
    """Return a list of evaluation report IDs that are due for delivery."""
    now_with_buffer = dt.datetime.now(tz=dt.UTC) + dt.timedelta(minutes=inputs.buffer_minutes)

    @database_sync_to_async(thread_sensitive=False)
    def get_report_ids() -> list[str]:
        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport

        return [
            str(pk)
            for pk in EvaluationReport.objects.filter(
                next_delivery_date__lte=now_with_buffer,
                enabled=True,
                deleted=False,
            ).values_list("id", flat=True)
        ]

    report_ids = await get_report_ids()
    await logger.ainfo(f"Found {len(report_ids)} due evaluation reports")
    return FetchDueEvalReportsOutput(report_ids=report_ids)


@temporalio.activity.defn
async def prepare_report_context_activity(
    inputs: PrepareReportContextInput,
) -> PrepareReportContextOutput:
    """Load evaluation from Postgres and calculate time windows."""

    @database_sync_to_async(thread_sensitive=False)
    def prepare() -> PrepareReportContextOutput:
        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport

        report = EvaluationReport.objects.select_related("evaluation").get(id=inputs.report_id)
        evaluation = report.evaluation
        now = dt.datetime.now(tz=dt.UTC)

        # Period end is now, period start depends on context
        period_end = now
        freq_deltas = {
            "hourly": dt.timedelta(hours=1),
            "daily": dt.timedelta(days=1),
            "weekly": dt.timedelta(weeks=1),
        }

        if inputs.manual:
            # Manual "Generate now": always look back one full frequency period
            # so the user always gets a meaningful report regardless of last delivery
            period_start = now - freq_deltas.get(report.frequency, dt.timedelta(days=1))
        elif report.last_delivered_at:
            period_start = report.last_delivered_at
        else:
            # First scheduled run: look back one period
            period_start = now - freq_deltas.get(report.frequency, dt.timedelta(days=1))

        # Previous period for comparison (same duration, shifted back)
        period_duration = period_end - period_start
        previous_period_start = period_start - period_duration

        return PrepareReportContextOutput(
            report_id=str(report.id),
            team_id=report.team_id,
            evaluation_id=str(evaluation.id),
            evaluation_name=evaluation.name,
            evaluation_description=evaluation.description or "",
            evaluation_prompt=evaluation.evaluation_config.get("prompt", ""),
            evaluation_type=evaluation.evaluation_type,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            previous_period_start=previous_period_start.isoformat(),
        )

    return await prepare()


@temporalio.activity.defn
async def run_eval_report_agent_activity(
    inputs: RunEvalReportAgentInput,
) -> RunEvalReportAgentOutput:
    """Run the LLM report agent."""
    async with Heartbeater():
        await logger.ainfo(
            "Running eval report agent",
            report_id=inputs.report_id,
            evaluation_id=inputs.evaluation_id,
        )

        @database_sync_to_async(thread_sensitive=False)
        def run_agent():
            from posthog.temporal.llm_analytics.eval_reports.report_agent import run_eval_report_agent

            return run_eval_report_agent(
                team_id=inputs.team_id,
                evaluation_id=inputs.evaluation_id,
                evaluation_name=inputs.evaluation_name,
                evaluation_description=inputs.evaluation_description,
                evaluation_prompt=inputs.evaluation_prompt,
                evaluation_type=inputs.evaluation_type,
                period_start=inputs.period_start,
                period_end=inputs.period_end,
                previous_period_start=inputs.previous_period_start,
            )

        content, metadata = await run_agent()

        return RunEvalReportAgentOutput(
            report_id=inputs.report_id,
            content=content.to_dict(),
            metadata=metadata.to_dict() if metadata else None,
            period_start=inputs.period_start,
            period_end=inputs.period_end,
        )


@temporalio.activity.defn
async def store_report_run_activity(
    inputs: StoreReportRunInput,
) -> StoreReportRunOutput:
    """Save the generated report as an EvaluationReportRun and emit a $ai_evaluation_report event."""

    @database_sync_to_async(thread_sensitive=False)
    def store() -> str:
        import uuid

        from posthog.models.event.util import create_event
        from posthog.models.team import Team

        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReportRun

        run = EvaluationReportRun.objects.create(
            report_id=inputs.report_id,
            content=inputs.content,
            metadata=inputs.metadata or {},
            period_start=inputs.period_start,
            period_end=inputs.period_end,
        )

        # Emit $ai_evaluation_report event to ClickHouse
        team = Team.objects.get(id=inputs.team_id)
        metadata = inputs.metadata or {}

        # Collect all referenced generation IDs across sections
        all_referenced_ids: list[str] = []
        for section_data in (inputs.content or {}).values():
            if isinstance(section_data, dict):
                all_referenced_ids.extend(section_data.get("referenced_generation_ids", []))

        properties: dict = {
            "$ai_evaluation_id": inputs.evaluation_id,
            "$ai_evaluation_report_id": str(run.report_id),
            "$ai_evaluation_report_run_id": str(run.id),
            "$ai_report_period_start": inputs.period_start,
            "$ai_report_period_end": inputs.period_end,
            # Metrics for querying/alerting
            "$ai_report_total_runs": metadata.get("total_runs", 0),
            "$ai_report_pass_count": metadata.get("pass_count", 0),
            "$ai_report_fail_count": metadata.get("fail_count", 0),
            "$ai_report_na_count": metadata.get("na_count", 0),
            "$ai_report_pass_rate": metadata.get("pass_rate", 0.0),
            "$ai_report_previous_pass_rate": metadata.get("previous_pass_rate"),
            # Full content for downstream consumption
            "$ai_report_content": inputs.content,
            "$ai_report_referenced_generation_ids": all_referenced_ids,
        }

        create_event(
            event_uuid=uuid.uuid4(),
            event="$ai_evaluation_report",
            team=team,
            distinct_id=f"eval_report_{inputs.team_id}",
            properties=properties,
        )

        return str(run.id)

    run_id = await store()
    return StoreReportRunOutput(report_run_id=run_id)


@temporalio.activity.defn
async def deliver_report_activity(
    inputs: DeliverReportInput,
) -> None:
    """Deliver the report via configured delivery targets (email/Slack)."""
    async with Heartbeater():
        await logger.ainfo(
            "Delivering evaluation report",
            report_id=inputs.report_id,
            report_run_id=inputs.report_run_id,
        )

        @database_sync_to_async(thread_sensitive=False)
        def deliver():
            from posthog.temporal.llm_analytics.eval_reports.delivery import deliver_report

            deliver_report(
                report_id=inputs.report_id,
                report_run_id=inputs.report_run_id,
            )

        await deliver()


@temporalio.activity.defn
async def update_next_delivery_date_activity(
    inputs: UpdateNextDeliveryDateInput,
) -> None:
    """Update the report's next_delivery_date and last_delivered_at."""

    @database_sync_to_async(thread_sensitive=False)
    def update():
        import datetime as dt_mod

        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport

        report = EvaluationReport.objects.get(id=inputs.report_id)
        report.last_delivered_at = dt_mod.datetime.now(tz=dt_mod.UTC)
        report.set_next_delivery_date()
        report.save(update_fields=["last_delivered_at", "next_delivery_date"])

    await update()
