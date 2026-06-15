import json
from datetime import timedelta

from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer
from posthog.temporal.utils import CDPProducerWorkflowInputs

LOGGER = get_logger(__name__)


@activity.defn
async def produce_to_cdp_kafka_activity(inputs: CDPProducerWorkflowInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    await CDPProducer(
        team_id=inputs.team_id, schema_id=inputs.schema_id, job_id=inputs.job_id, logger=logger
    ).produce_to_kafka_from_s3()


@workflow.defn(name="dwh-cdp-producer-job")
class CDPProducerJobWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CDPProducerWorkflowInputs:
        loaded = json.loads(inputs[0])
        return CDPProducerWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: CDPProducerWorkflowInputs) -> None:
        await workflow.execute_activity(
            produce_to_cdp_kafka_activity,
            inputs,
            start_to_close_timeout=timedelta(hours=24),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
