from contextlib import AbstractContextManager

from django.db import transaction

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ...facade.enums import CheckRunStatus
from ...logic.contracts import PreparedQuestion
from ...logic.jev_execution import INCOMPLETE_ERROR, DurableQuestionRunner
from ...logic.runner import record_unrunnable_check
from ...models import DataQualityCheck, DataQualityCheckRun, DataQualityQuestionExecution, DataQualitySuiteRun
from ..contracts import BatchOutcome, FinishQuestionInputs, QuestionChunkInputs, QuestionInputs

LOGGER = get_logger(__name__)


def _start(inputs: QuestionInputs) -> DurableQuestionRunner:
    return DurableQuestionRunner.start(inputs.team_id, inputs.suite_run_id, inputs.check_id)


def _question_tags(runner: DurableQuestionRunner) -> AbstractContextManager[object]:
    return tags_context(
        product=Product.DATA_QUALITY,
        feature=Feature.DATA_QUALITY_CHECK,
        data_quality_check_id=str(runner.execution.definition_id),
        data_quality_run_id=str(runner.execution.id),
        data_quality_check_type="question",
        data_quality_subject_type="table",
        data_quality_subject_id=str(runner.execution.subject_uuid),
    )


@activity.defn
async def prepare_question_activity(inputs: QuestionInputs) -> PreparedQuestion:
    async with Heartbeater():
        try:
            runner = await database_sync_to_async_pool(_start)(inputs)
            with _question_tags(runner):
                pending = await database_sync_to_async_pool(runner.begin_prepare)()
                # The scan runs on this event loop; it submits its own executor jobs, so no pool thread may wait on it.
                frozen = await runner.freeze_inputs(*pending) if pending is not None else None
                return await database_sync_to_async_pool(runner.complete_prepare)(frozen)
        except Exception as error:
            # The ApplicationError is deliberately generic, so the cause is only recoverable from this log.
            LOGGER.exception(
                "question_prepare_failed",
                team_id=inputs.team_id,
                suite_run_id=inputs.suite_run_id,
                check_id=inputs.check_id,
                reason=type(error).__name__,
            )
            raise ApplicationError(INCOMPLETE_ERROR) from None


def _chunk(inputs: QuestionChunkInputs) -> None:
    runner = DurableQuestionRunner(inputs.team_id, inputs.execution_id)
    with _question_tags(runner):
        runner.chunk(inputs.chunk_index)


@activity.defn
async def run_question_chunk_activity(inputs: QuestionChunkInputs) -> None:
    async with Heartbeater():
        try:
            await database_sync_to_async_pool(_chunk)(inputs)
        except Exception as error:
            LOGGER.exception(
                "question_chunk_failed",
                team_id=inputs.team_id,
                execution_id=inputs.execution_id,
                chunk_index=inputs.chunk_index,
                reason=type(error).__name__,
            )
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
            if check is None or check.deleted or not check.enabled:
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
