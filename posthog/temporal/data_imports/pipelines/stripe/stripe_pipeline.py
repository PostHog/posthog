from dataclasses import dataclass
from typing import Dict

import dlt
from django.conf import settings
from dlt.pipeline.exceptions import PipelineStepFailed

from posthog.warehouse.models import ExternalDataSource

from posthog.temporal.data_imports.pipelines.stripe.helpers import stripe_pagination
from posthog.temporal.data_imports.pipelines.stripe.settings import ENDPOINTS

import os
from temporalio import activity
from posthog.temporal.common.utils import (
    DataImportHeartbeatDetails,
    should_resume_from_activity_heartbeat,
)
import structlog
import asyncio


@dataclass
class PipelineInputs:
    source_id: str
    dataset_name: str
    job_type: str
    team_id: int


@dataclass
class SourceColumnType:
    name: str
    data_type: str
    nullable: bool


@dataclass
class SourceSchema:
    resource: str
    name: str
    columns: Dict[str, SourceColumnType]
    write_disposition: str


@dataclass
class StripeJobInputs(PipelineInputs):
    stripe_secret_key: str


def create_pipeline(inputs: PipelineInputs):
    pipeline_name = f"{inputs.job_type}_pipeline_{inputs.team_id}_source_{inputs.source_id}"
    pipelines_dir = f"{os.getcwd()}/.dlt/{inputs.team_id}/{inputs.source_id}/{inputs.job_type}"
    return dlt.pipeline(
        pipeline_name=pipeline_name,
        pipelines_dir=pipelines_dir,  # workers can be created and destroyed so it doesn't matter where the metadata gets put temporarily
        destination="filesystem",
        dataset_name=inputs.dataset_name,
        credentials={
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
        },
    )


async def run_stripe_pipeline(inputs: StripeJobInputs) -> None:
    ordered_endpoints = ENDPOINTS

    # basic logger for now
    logger = structlog.get_logger(__name__)
    should_resume, details = await should_resume_from_activity_heartbeat(activity, DataImportHeartbeatDetails, logger)

    if should_resume:
        ordered_endpoints = ordered_endpoints[ordered_endpoints.index(details.endpoint) :]
        logger.info(f"Resuming from {details.endpoint} with cursor {details.cursor}")

    endpoint = ordered_endpoints[0]
    cursor = None

    async def worker_shutdown_handler():
        """Handle the Worker shutting down by heart-beating our latest status."""
        await activity.wait_for_worker_shutdown()
        activity.heartbeat(endpoint, cursor)

    asyncio.create_task(worker_shutdown_handler())

    for endpoint in ordered_endpoints:
        if should_resume and endpoint == details.endpoint:
            starting_after = details.cursor
        else:
            starting_after = None

        async for item, cursor in stripe_pagination(inputs.stripe_secret_key, endpoint, starting_after=starting_after):
            try:
                pipeline = create_pipeline(inputs)
                pipeline.run(item, table_name=endpoint.lower(), loader_file_format="parquet")
                pipeline.deactivate()
                activity.heartbeat(endpoint, cursor)
            except PipelineStepFailed:
                # TODO: log
                raise


PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING = {ExternalDataSource.Type.STRIPE: ENDPOINTS}
PIPELINE_TYPE_INPUTS_MAPPING = {ExternalDataSource.Type.STRIPE: StripeJobInputs}
PIPELINE_TYPE_RUN_MAPPING = {ExternalDataSource.Type.STRIPE: run_stripe_pipeline}
