from datetime import UTC, datetime

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from products.data_modeling.backend.facade import api as data_modeling_facade

from ...facade.enums import SubjectType, SuiteRunTrigger
from ...models import DataQualityCheck, DataQualitySuiteRun
from ..contracts import PreparedSuite, RunCheckSuiteInputs

LOGGER = get_logger(__name__)

# Checks are individually cheap, so batching keeps activity overhead from dominating. Small enough
# that one slow warehouse query cannot push a batch past its start-to-close timeout.
CHECKS_PER_BATCH = 25


@activity.defn
async def prepare_check_suite_activity(inputs: RunCheckSuiteInputs) -> PreparedSuite:
    return await sync_to_async(_prepare)(inputs)


def _prepare(inputs: RunCheckSuiteInputs) -> PreparedSuite:
    checks = _select_checks(inputs)
    suite_run = _suite_run(inputs)

    check_ids = [str(check_id) for check_id in checks]
    batches = [check_ids[start : start + CHECKS_PER_BATCH] for start in range(0, len(check_ids), CHECKS_PER_BATCH)]
    LOGGER.info("Prepared check suite", suite_run_id=str(suite_run.id), checks=len(check_ids), batches=len(batches))
    return PreparedSuite(suite_run_id=str(suite_run.id), batches=batches)


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
        subject_type=inputs.subject_type if len(inputs.subject_uuids) == 1 else "",
        subject_uuid=inputs.subject_uuids[0] if len(inputs.subject_uuids) == 1 else None,
        data_modeling_job_id=inputs.data_modeling_job_id,
        workflow_id=info.workflow_id or "",
        workflow_run_id=info.workflow_run_id or "",
        started_at=datetime.now(UTC),
    )


def _select_checks(inputs: RunCheckSuiteInputs) -> list[str]:
    runnable = DataQualityCheck.objects.for_team(inputs.team_id).filter(enabled=True, deleted=False)

    if inputs.check_ids:
        runnable = runnable.filter(id__in=inputs.check_ids)
    else:
        subject_type, subject_uuids = _resolve_selector(inputs)
        if not subject_uuids:
            return []
        runnable = runnable.filter(subject_type=subject_type, subject_uuid__in=subject_uuids)

    if inputs.trigger == SuiteRunTrigger.MATERIALIZATION:
        runnable = runnable.filter(run_on_materialization=True)

    return [str(check_id) for check_id in runnable.values_list("id", flat=True)]


def _resolve_selector(inputs: RunCheckSuiteInputs) -> tuple[str, list[str]]:
    if inputs.node_ids:
        return SubjectType.VIEW, data_modeling_facade.get_saved_query_ids_for_nodes(inputs.team_id, inputs.node_ids)
    return inputs.subject_type, inputs.subject_uuids
