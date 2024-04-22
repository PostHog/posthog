from dataclasses import dataclass
from typing import Dict, Literal
from uuid import UUID

import dlt
from django.conf import settings
from dlt.pipeline.exceptions import PipelineStepFailed

import asyncio
import os
from posthog.settings.base_variables import TEST
from structlog.typing import FilteringBoundLogger
from dlt.sources import DltSource
from collections import Counter


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

    def __init__(
        self, inputs: PipelineInputs, source: DltSource, logger: FilteringBoundLogger, incremental: bool = False
    ):
        self.inputs = inputs
        self.logger = logger
        if incremental:
            # Incremental syncs: Assuming each page is 100 items for now so bound each run at 50_000 items
            self.source = source.add_limit(500)
        else:
            self.source = source

        self._incremental = incremental

    @property
    def _get_pipeline_name_base(self):
        return f"{self.inputs.job_type}_pipeline_{self.inputs.team_id}_run"

    def _get_pipeline_name(self):
        base = self._get_pipeline_name_base

        if self._incremental:
            return f"{base}_{self.inputs.source_id}"

        return f"{base}_{self.inputs.run_id}"

    @property
    def _get_pipelines_dir_base(self):
        return f"{os.getcwd()}/.dlt/{self.inputs.team_id}"

    def _get_pipelines_dir(self):
        base = self._get_pipelines_dir_base

        if self._incremental:
            return f"{base}/{self.inputs.source_id}/{self.inputs.job_type}"

        return f"{base}/{self.inputs.run_id}/{self.inputs.job_type}"

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

    def _run(self) -> Dict[str, int]:
        pipeline = self._create_pipeline()

        total_counts: Counter = Counter({})

        if self._incremental:
            # will get overwritten
            counts: Counter = Counter({"start": 1})

            while counts:
                pipeline.run(self.source, loader_file_format=self.loader_file_format)

                row_counts = pipeline.last_trace.last_normalize_info.row_counts
                # Remove any DLT tables from the counts
                filtered_rows = filter(lambda pair: not pair[0].startswith("_dlt"), row_counts.items())
                counts = Counter(dict(filtered_rows))
                total_counts = counts + total_counts
        else:
            pipeline.run(self.source, loader_file_format=self.loader_file_format)
            row_counts = pipeline.last_trace.last_normalize_info.row_counts
            filtered_rows = filter(lambda pair: not pair[0].startswith("_dlt"), row_counts.items())
            counts = Counter(dict(filtered_rows))
            total_counts = total_counts + counts

        return dict(total_counts)

    async def run(self) -> Dict[str, int]:
        try:
            return await asyncio.to_thread(self._run)
        except PipelineStepFailed:
            self.logger.error(f"Data import failed for endpoint")
            raise
