from datetime import UTC, datetime

from django.db import models

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade import api as data_modeling_facade

from ...facade.enums import SubjectType, SuiteRunTrigger
from ...logic.checks import live_subject_checks
from ...logic.flags import get_data_quality_checks_flag_for_team_id
from ...logic.metric_schedules import MetricScheduleKey, MetricSchedules
from ...models import DataQualityCheck, DataQualitySuiteRun
from ..contracts import PreparedSuite, RunCheckSuiteInputs

LOGGER = get_logger(__name__)

CHECKS_PER_BATCH = 25


@activity.defn
async def prepare_check_suite_activity(inputs: RunCheckSuiteInputs) -> PreparedSuite:
    schedule_enabled = True
    if inputs.trigger == SuiteRunTrigger.SCHEDULED:
        if not inputs.schedule_id:
            raise ValueError("Scheduled suites require a schedule identifier")
        key = MetricScheduleKey.parse(inputs.schedule_id)
        if key.team_id != inputs.team_id or inputs.metric_ids != [str(key.metric_id)]:
            raise ValueError("Schedule subject does not match suite inputs")
        schedule = await MetricSchedules(await async_connect()).describe(key)
        schedule_enabled = schedule is not None and not schedule.schedule.state.paused
    return await sync_to_async(_prepare)(inputs, schedule_enabled=schedule_enabled)


def _prepare(inputs: RunCheckSuiteInputs, *, schedule_enabled: bool = True) -> PreparedSuite:
    checks = _select_checks(inputs) if _checks_enabled(inputs.team_id) and schedule_enabled else []
    suite_run = _suite_run(inputs)

    check_ids = [str(check_id) for check_id in checks]
    batches = [check_ids[start : start + CHECKS_PER_BATCH] for start in range(0, len(check_ids), CHECKS_PER_BATCH)]
    LOGGER.info("Prepared check suite", suite_run_id=str(suite_run.id), checks=len(check_ids), batches=len(batches))
    return PreparedSuite(suite_run_id=str(suite_run.id), batches=batches)


def _checks_enabled(team_id: int) -> bool:
    """Fail on a flag the lookup could not read, rather than read it as off.

    An off flag is a kill switch and must still stop the suite. An unreadable flag is a transient
    fault, and treating it as off would consume a scheduled occurrence, stamp a run that validated
    nothing, and report success. Raising lets the activity retry.
    """
    enabled = get_data_quality_checks_flag_for_team_id(team_id)
    if enabled is None:
        raise RuntimeError(f"Could not read the data quality checks flag for team {team_id}.")
    return enabled


def _suite_run(inputs: RunCheckSuiteInputs) -> DataQualitySuiteRun:
    """Adopt the row the API already created, or make one for a trigger that had nobody to hand it to.

    Keyed on ``workflow_id`` so a retry is idempotent: an attempt that commits the row and then dies
    before Temporal records its result must adopt that row on the next attempt, not strand an orphan
    that nothing ever finalizes.
    """
    info = activity.info()
    runs = DataQualitySuiteRun.objects.for_team(inputs.team_id)
    if inputs.suite_run_id:
        suite_run = runs.get(id=inputs.suite_run_id)
        suite_run.workflow_run_id = info.workflow_run_id or ""
        suite_run.save(update_fields=["workflow_run_id", "updated_at"])
        return suite_run

    if info.workflow_id:
        existing = runs.filter(workflow_id=info.workflow_id).first()
        if existing is not None:
            return existing

    return runs.create(
        team_id=inputs.team_id,
        trigger=inputs.trigger,
        created_by_id=inputs.created_by_id,
        data_modeling_job_id=inputs.data_modeling_job_id,
        workflow_id=info.workflow_id or "",
        workflow_run_id=info.workflow_run_id or "",
        started_at=datetime.now(UTC),
        **_single_subject_fields(inputs),
    )


def _single_subject_fields(inputs: RunCheckSuiteInputs) -> dict[str, str]:
    """The subject columns to record, empty when the run spans more than one subject.

    Leaving them out lets the model's own column defaults stand, which is what "this run has no one
    subject" looks like on the row.
    """
    subjects = [
        (subject_type, subject_uuid)
        for subject_type, identifiers in (
            (SubjectType.VIEW, inputs.saved_query_ids),
            (SubjectType.TABLE, inputs.table_ids),
            (SubjectType.METRIC, inputs.metric_ids),
        )
        for subject_uuid in identifiers
    ]
    if len(subjects) == 1 and not inputs.node_ids and not inputs.check_ids:
        return {"subject_type": subjects[0][0], "subject_uuid": subjects[0][1]}
    return {}


def _select_checks(inputs: RunCheckSuiteInputs) -> list[str]:
    runnable = live_subject_checks(
        DataQualityCheck.objects.for_team(inputs.team_id).filter(enabled=True, deleted=False)
    )

    if inputs.check_ids:
        runnable = runnable.filter(id__in=inputs.check_ids)
    else:
        saved_query_ids = list(inputs.saved_query_ids)
        if inputs.node_ids:
            saved_query_ids += data_modeling_facade.get_saved_query_ids_for_nodes(inputs.team_id, inputs.node_ids)
        if not saved_query_ids and not inputs.table_ids and not inputs.metric_ids:
            return []
        subject_filter = models.Q(saved_query_id__in=saved_query_ids)
        if inputs.table_ids:
            subject_filter |= models.Q(table_id__in=inputs.table_ids)
        if inputs.metric_ids:
            subject_filter |= models.Q(metric_id__in=inputs.metric_ids)
        runnable = runnable.filter(subject_filter)

    return [str(check_id) for check_id in runnable.values_list("id", flat=True)]
