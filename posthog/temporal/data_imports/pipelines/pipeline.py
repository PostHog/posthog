from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import dlt
from django.conf import settings
from dlt.pipeline.exceptions import PipelineStepFailed

import asyncio
import os
from posthog.settings.base_variables import TEST
from structlog.typing import FilteringBoundLogger
from dlt.sources import DltSource


@dataclass
class PipelineInputs:
    source_id: UUID
    run_id: str
    schema_id: UUID
    dataset_name: str
    job_type: str
    team_id: int


class DataImportPipeline:
    loader_file_format: Literal["parquet"] = "parquet"

    def __init__(self, inputs: PipelineInputs, source: DltSource, logger: FilteringBoundLogger):
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
                "region_name": settings.AIRBYTE_BUCKET_REGION,
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

    def _run(self) -> dict[str, int]:
        pipeline = self._create_pipeline()
        pipeline.run(self.source, loader_file_format=self.loader_file_format)

        row_counts = pipeline.last_trace.last_normalize_info.row_counts
        # Remove any DLT tables from the counts
        filtered_rows = filter(lambda pair: not pair[0].startswith("_dlt"), row_counts.items())

        return dict(filtered_rows)

    async def run(self) -> dict[str, int]:
        try:
            return await asyncio.to_thread(self._run)
        except PipelineStepFailed:
            self.logger.error(f"Data import failed for endpoint")
            raise
