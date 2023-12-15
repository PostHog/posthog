from dataclasses import dataclass
from typing import Dict
from uuid import UUID

import dlt
from django.conf import settings
from dlt.pipeline.exceptions import PipelineStepFailed

from posthog.warehouse.models import ExternalDataSource
from posthog.temporal.data_imports.pipelines.stripe.helpers import stripe_source
from posthog.temporal.data_imports.pipelines.stripe.settings import ENDPOINTS
from posthog.temporal.common.logger import bind_temporal_worker_logger
import asyncio
import os
from posthog.settings.base_variables import TEST


@dataclass
class PipelineInputs:
    source_id: UUID
    run_id: str
    schemas: list[str]
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
    pipeline_name = f"{inputs.job_type}_pipeline_{inputs.team_id}_run_{inputs.run_id}"
    pipelines_dir = f"{os.getcwd()}/.dlt/{inputs.team_id}/{inputs.run_id}/{inputs.job_type}"

    return dlt.pipeline(
        pipeline_name=pipeline_name,
        pipelines_dir=pipelines_dir,
        destination=dlt.destinations.filesystem(
            credentials={
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT if TEST else None,
            },
            bucket_url=settings.BUCKET_URL,  # type: ignore
        ),
        dataset_name=inputs.dataset_name,
    )


def _run_pipeline(inputs: StripeJobInputs):
    pipeline = create_pipeline(inputs)
    source = stripe_source(inputs.stripe_secret_key, tuple(inputs.schemas))
    pipeline.run(source, loader_file_format="parquet")


# a temporal activity
async def run_stripe_pipeline(inputs: StripeJobInputs) -> None:
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)
    schemas = inputs.schemas
    if not schemas:
        logger.info(f"No schemas found for source id {inputs.source_id}")
        return

    try:
        await asyncio.to_thread(_run_pipeline, inputs)
    except PipelineStepFailed:
        logger.error(f"Data import failed for endpoint")
        raise


PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING = {ExternalDataSource.Type.STRIPE: ENDPOINTS}
PIPELINE_TYPE_INPUTS_MAPPING = {ExternalDataSource.Type.STRIPE: StripeJobInputs}
PIPELINE_TYPE_RUN_MAPPING = {ExternalDataSource.Type.STRIPE: run_stripe_pipeline}
