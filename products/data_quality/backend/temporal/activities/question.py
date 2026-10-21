from django.db import transaction

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater

from ...facade.enums import CheckRunStatus
from ...logic.contracts import PreparedQuestion
from ...logic.jev_execution import INCOMPLETE_ERROR, DurableQuestionRunner
from ...logic.runner import record_unrunnable_check
from ...models import DataQualityCheck, DataQualityCheckRun, DataQualityQuestionExecution, DataQualitySuiteRun
from ..contracts import BatchOutcome, FinishQuestionInputs, QuestionChunkInputs, QuestionInputs


def _prepare(inputs: QuestionInputs) -> PreparedQuestion:
    runner = DurableQuestionRunner.start(inputs.team_id, inputs.suite_run_id, inputs.check_id)
    with tags_context(
        product=Product.DATA_QUALITY,
        feature=Feature.DATA_QUALITY_CHECK,
        data_quality_check_id=inputs.check_id,
        data_quality_run_id=str(runner.execution.id),
        data_quality_check_type="question",
        data_quality_subject_type="table",
        data_quality_subject_id=str(runner.execution.subject_uuid),
    ):
        return runner.prepare()


@activity.defn
async def prepare_question_activity(inputs: QuestionInputs) -> PreparedQuestion:
    async with Heartbeater():
        try:
            return await database_sync_to_async_pool(_prepare)(inputs)
        except Exception:
            raise ApplicationError(INCOMPLETE_ERROR) from None


def _chunk(inputs: QuestionChunkInputs) -> None:
    runner = DurableQuestionRunner(inputs.team_id, inputs.execution_id)
    with tags_context(
        product=Product.DATA_QUALITY,
        feature=Feature.DATA_QUALITY_CHECK,
        data_quality_check_id=str(runner.execution.definition_id),
        data_quality_run_id=inputs.execution_id,
        data_quality_check_type="question",
        data_quality_subject_type="table",
        data_quality_subject_id=str(runner.execution.subject_uuid),
    ):
        runner.chunk(inputs.chunk_index)


@activity.defn
async def run_question_chunk_activity(inputs: QuestionChunkInputs) -> None:
    async with Heartbeater():
        try:
            await database_sync_to_async_pool(_chunk)(inputs)
        except Exception:
            raise ApplicationError(INCOMPLETE_ERROR) from None


def _finish(inputs: FinishQuestionInputs) -> BatchOutcome:
    execution = (
        DataQualityQuestionExecution.objects.for_team(inputs.team_id)
        .filter(suite_run_id=inputs.suite_run_id, definition_id=inputs.check_id)
        .first()
    )
    if execution is None:
        with transaction.atomic():
            check = (
                DataQualityCheck.objects.for_team(inputs.team_id).select_for_update().filter(id=inputs.check_id).first()
            )
            if check is None:
                return BatchOutcome(skipped=1)
            if (
                not DataQualityCheckRun.objects.for_team(inputs.team_id)
                .filter(suite_run_id=inputs.suite_run_id, quality_check_id=inputs.check_id)
                .exists()
            ):
                record_unrunnable_check(
                    check,
                    DataQualitySuiteRun.objects.for_team(inputs.team_id).get(id=inputs.suite_run_id),
                    Team.objects.get(id=inputs.team_id),
                    INCOMPLETE_ERROR,
                )
        return BatchOutcome(errored=1)
    result = DurableQuestionRunner(inputs.team_id, str(execution.id)).finish(errored=inputs.errored)
    return BatchOutcome(
        passed=int(result.status == CheckRunStatus.PASSED),
        failed=int(result.status == CheckRunStatus.FAILED),
        errored=int(result.status == CheckRunStatus.ERRORED),
        skipped=int(result.status == CheckRunStatus.SKIPPED),
    )


@activity.defn
async def finish_question_activity(inputs: FinishQuestionInputs) -> BatchOutcome:
    return await database_sync_to_async_pool(_finish)(inputs)
