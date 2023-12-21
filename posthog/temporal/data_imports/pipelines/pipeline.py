from dataclasses import dataclass
from uuid import UUID

import dlt
from django.conf import settings
from dlt.pipeline.exceptions import PipelineStepFailed

import asyncio
import os
from posthog.settings.base_variables import TEST
from structlog.typing import FilteringBoundLogger
from dlt.sources import DltResource


@dataclass
class PipelineInputs:
    source_id: UUID
    run_id: str
    schemas: list[str]
    dataset_name: str
    job_type: str
    team_id: int


class DataImportPipeline:
    loader_file_format = "parquet"

    def __init__(self, inputs: PipelineInputs, source: DltResource, logger: FilteringBoundLogger):
        self.inputs = inputs
        self.logger = logger
        self.source = source

    def _get_pipeline_name(self):
        return f"{self.inputs.job_type}_pipeline_{self.inputs.team_id}_run_{self.inputs.run_id}"

    def _get_pipelines_dir(self):
        return f"{os.getcwd()}/.dlt/{self.inputs.team_id}/{self.inputs.run_id}/{self.inputs.job_type}"

    def _get_destination(self):
        if TEST:
            credentials = {
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            }
        else:
            credentials = {
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            }

        return dlt.destinations.filesystem(
            credentials=credentials,
            bucket_url=settings.BUCKET_URL,  # type: ignore
        )

    def _create_pipeline(self):
        pipeline_name = self._get_pipeline_name()
        pipelines_dir = self._get_pipelines_dir()
        destination = self._get_destination()

        return dlt.pipeline(
            pipeline_name=pipeline_name,
            pipelines_dir=pipelines_dir,
            destination=destination,
            dataset_name=self.inputs.dataset_name,
        )

    def _get_schemas(self):
        if not self.inputs.schemas:
            self.logger.info(f"No schemas found for source id {self.inputs.source_id}")
            return None

        return self.inputs.schemas

    def _run(self):
        pipeline = self._create_pipeline()
        pipeline.run(self.source, loader_file_format=self.loader_file_format)

    async def run(self) -> None:
        schemas = self._get_schemas()
        if not schemas:
            return

        try:
            await asyncio.to_thread(self._run)
        except PipelineStepFailed:
            self.logger.error(f"Data import failed for endpoint")
            raise
