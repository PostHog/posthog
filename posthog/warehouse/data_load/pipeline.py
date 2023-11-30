from dataclasses import dataclass
from typing import Dict

import dlt
import s3fs
from django.conf import settings
from dlt.pipeline.exceptions import PipelineStepFailed

from posthog.warehouse.models import ExternalDataSource

from .stripe import ENDPOINTS, stripe_pagination

import os
import stripe

stripe.api_version = "2022-11-15"


@dataclass
class PipelineInputs:
    source_id: str
    dataset_name: str
    job_type: str
    team_id: int


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


PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING = {ExternalDataSource.Type.STRIPE: ENDPOINTS}


async def run_stripe_pipeline(inputs: StripeJobInputs) -> None:
    for endpoint in ENDPOINTS:
        async for item in stripe_pagination(inputs.stripe_secret_key, endpoint):
            try:
                pipeline = create_pipeline(inputs)
                pipeline.run(item, table_name=endpoint.lower(), loader_file_format="parquet")
                pipeline.deactivate()
            except PipelineStepFailed:
                # TODO: log
                raise


PIPELINE_TYPE_INPUTS_MAPPING = {ExternalDataSource.Type.STRIPE: StripeJobInputs}
PIPELINE_TYPE_RUN_MAPPING = {ExternalDataSource.Type.STRIPE: run_stripe_pipeline}


def get_s3fs():
    return s3fs.S3FileSystem(key=settings.AIRBYTE_BUCKET_KEY, secret=settings.AIRBYTE_BUCKET_SECRET)


# TODO: Make this a proper async function with boto3...
def move_draft_to_production(team_id: int, external_data_source_id: str):
    model = ExternalDataSource.objects.get(team_id=team_id, id=external_data_source_id)
    bucket_name = settings.BUCKET_URL
    s3 = get_s3fs()
    try:
        s3.copy(
            f"{bucket_name}/{model.draft_folder_path}",
            f"{bucket_name}/{model.draft_folder_path}_success",
            recursive=True,
        )
    except FileNotFoundError:
        # TODO: log
        pass

    try:
        s3.delete(f"{bucket_name}/{model.folder_path}", recursive=True)
    except FileNotFoundError:
        # This folder won't exist on initial run
        pass

    try:
        s3.copy(
            f"{bucket_name}/{model.draft_folder_path}_success", f"{bucket_name}/{model.folder_path}", recursive=True
        )
    except FileNotFoundError:
        pass

    s3.delete(f"{bucket_name}/{model.draft_folder_path}_success", recursive=True)
    s3.delete(f"{bucket_name}/{model.draft_folder_path}", recursive=True)
