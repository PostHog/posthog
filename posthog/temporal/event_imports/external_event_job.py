import json
import os
import datetime as dt
import dataclasses
import requests
from typing import Optional

from posthog.temporal.event_imports.utils import parse_amplitude_event, send_event_batch
from posthog.temporal.event_imports.sources.amplitude.file import (
    extract_zip_file,
    extract_gzipped_files,
    find_files_to_process,
    cleanup_temp_dir,
)
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync
from posthog.products.managed_migrations.models import ManagedMigration


@dataclasses.dataclass
class ExternalEventWorkflowInputs:
    team_id: int
    api_key: str
    secret_key: str
    posthog_api_key: str
    source: str
    job_id: str
    start_date: str
    end_date: str
    posthog_domain: str = "https://app.dev.posthog.com"


@dataclasses.dataclass
class FetchAmplitudeDataActivityInputs:
    team_id: int
    api_key: str
    secret_key: str
    start_date: str
    end_date: str
    file_path: str
    job_id: str


@dataclasses.dataclass
class UncompressFileActivityInputs:
    team_id: int
    file_path: str
    uncompressed_dir: str


@dataclasses.dataclass
class ProcessEventsActivityInputs:
    team_id: int
    job_id: str
    file_path: str
    posthog_api_key: str
    posthog_domain: str
    batch_size: int = 20


@dataclasses.dataclass
class UpdateMigrationStatusActivityInputs:
    team_id: int
    job_id: str
    status: str
    error: Optional[str] = None
    events_processed: int = 0


@workflow.defn(name="external-event-job")
class ExternalEventJobWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExternalEventWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ExternalEventWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ExternalEventWorkflowInputs):
        start_dt = dt.datetime.fromisoformat(inputs.start_date)
        end_dt = dt.datetime.fromisoformat(inputs.end_date)
        logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)

        source_handlers = {"amplitude": self._handle_amplitude_import}

        source = inputs.source.lower()
        handler = source_handlers.get(source)

        if not handler:
            logger.error(f"External event import source '{inputs.source}' is not supported")

            await workflow.execute_activity(
                update_migration_status_activity,
                UpdateMigrationStatusActivityInputs(
                    team_id=inputs.team_id,
                    job_id=inputs.job_id,
                    status=ManagedMigration.Status.FAILED,
                    error=f"Data source '{inputs.source}' is not supported",
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            return 0

        try:
            events_processed = await handler(inputs, start_dt, end_dt)

            await workflow.execute_activity(
                update_migration_status_activity,
                UpdateMigrationStatusActivityInputs(
                    team_id=inputs.team_id,
                    job_id=inputs.job_id,
                    status=ManagedMigration.Status.COMPLETED,
                    events_processed=events_processed,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            return events_processed

        except Exception:
            await workflow.execute_activity(
                update_migration_status_activity,
                UpdateMigrationStatusActivityInputs(
                    team_id=inputs.team_id,
                    job_id=inputs.job_id,
                    status=ManagedMigration.Status.FAILED,
                    error="Processing failed",
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise

    async def _handle_amplitude_import(
        self, inputs: ExternalEventWorkflowInputs, start_dt: dt.datetime, end_dt: dt.datetime
    ) -> int:
        """Handler for Amplitude data imports"""
        total_processed_events = 0
        base_temp_dir = f"/tmp/posthog/amplitude_import/{inputs.team_id}/{inputs.job_id}"
        temp_dir = None

        try:
            current_start = start_dt
            while current_start < end_dt:
                current_end = min(current_start + dt.timedelta(hours=1), end_dt)

                current_start_str = current_start.isoformat()
                current_end_str = current_end.isoformat()

                chunk_id = f"{current_start_str}-{current_end_str}"
                temp_dir = f"{base_temp_dir}/{chunk_id}"
                compressed_file_path = f"{temp_dir}/amplitude_import.json.zip"
                uncompressed_file_path_dir = f"{temp_dir}/uncompressed"

                os.makedirs(temp_dir, exist_ok=True)
                os.makedirs(uncompressed_file_path_dir, exist_ok=True)

                fetch_inputs = FetchAmplitudeDataActivityInputs(
                    team_id=inputs.team_id,
                    api_key=inputs.api_key,
                    secret_key=inputs.secret_key,
                    start_date=current_start_str,
                    end_date=current_end_str,
                    file_path=compressed_file_path,
                    job_id=inputs.job_id,
                )

                await workflow.execute_activity(
                    fetch_amplitude_data_activity,
                    fetch_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                uncompress_inputs = UncompressFileActivityInputs(
                    team_id=inputs.team_id,
                    file_path=compressed_file_path,
                    uncompressed_dir=uncompressed_file_path_dir,
                )

                await workflow.execute_activity(
                    uncompress_file_activity,
                    uncompress_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                process_inputs = ProcessEventsActivityInputs(
                    team_id=inputs.team_id,
                    job_id=inputs.job_id,
                    file_path=uncompressed_file_path_dir,
                    posthog_api_key=inputs.posthog_api_key,
                    posthog_domain=inputs.posthog_domain,
                    batch_size=20,
                )

                chunk_processed_events = await workflow.execute_activity(
                    process_events_activity,
                    process_inputs,
                    start_to_close_timeout=dt.timedelta(hours=1),
                    heartbeat_timeout=dt.timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_interval=dt.timedelta(seconds=60),
                        maximum_attempts=3,
                    ),
                )

                total_processed_events += chunk_processed_events

                cleanup_temp_dir(temp_dir)

                current_start = current_end

        except exceptions.ActivityError:
            raise
        except Exception:
            raise
        finally:
            if temp_dir:
                cleanup_temp_dir(temp_dir)

        return total_processed_events


@activity.defn
async def fetch_amplitude_data_activity(inputs: FetchAmplitudeDataActivityInputs) -> str:
    """
    Fetches data from Amplitude API and saves it to a file.
    Returns the path to the file.
    """
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    logger.info(f"Fetching Amplitude data for job {inputs.job_id}")

    url = "https://amplitude.com/api/2/export"

    auth = (inputs.api_key, inputs.secret_key)

    params = {
        "start": dt.datetime.fromisoformat(inputs.start_date).strftime("%Y%m%dT%H"),
        "end": dt.datetime.fromisoformat(inputs.end_date).strftime("%Y%m%dT%H"),
    }

    response = requests.get(url, auth=auth, params=params, stream=True, timeout=(30, 300))

    if response.status_code == 200:
        total_size = 0
        with open(inputs.file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)

        logger.info(f"Download complete. Total size: {total_size / (1024*1024):.2f} MB")
        return inputs.file_path
    else:
        logger.error(f"Failed to fetch data from Amplitude: {response.status_code} {response.text}")
        raise Exception(f"Failed to fetch data from Amplitude: {response.status_code} {response.text}")


@activity.defn
async def uncompress_file_activity(inputs: UncompressFileActivityInputs) -> str:
    """
    Uncompresses the file downloaded from Amplitude
    Returns the path to directory containing the uncompressed files.
    """
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    logger.info(f"Uncompressing file {inputs.file_path}")

    extract_dir = inputs.uncompressed_dir

    extract_zip_file(inputs.file_path, extract_dir)
    logger.info(f"Initial extraction complete")

    extract_gzipped_files(extract_dir)

    logger.info(f"All files decompressed in {extract_dir}")
    return extract_dir


@activity.defn
async def process_events_activity(inputs: ProcessEventsActivityInputs) -> int:
    """
    Processes the events in the uncompressed files and sends them to PostHog.
    Returns the number of events processed.
    """
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    logger.info(f"Processing events for job {inputs.job_id}")

    total_processed = 0

    file_paths = find_files_to_process(inputs.file_path)

    logger.info(f"Found {len(file_paths)} files to process")

    if not file_paths:
        logger.info(f"No files found to process in {inputs.file_path} or its subdirectories")
        return 0

    for file_idx, file_path in enumerate(file_paths):
        batch = []
        processed_in_file = 0
        with open(file_path) as f:
            for line in f:
                if not line.strip():
                    continue

                ph_event = parse_amplitude_event(line.strip())
                if ph_event:
                    batch.append(ph_event)

                if len(batch) >= inputs.batch_size:
                    processed = send_event_batch(batch, inputs.posthog_api_key, inputs.posthog_domain)
                    total_processed += processed
                    processed_in_file += processed
                    batch = []

            # Send any remaining events in the batch
            if batch:
                processed = send_event_batch(batch, inputs.posthog_api_key, inputs.posthog_domain)
                total_processed += processed
                processed_in_file += processed
        logger.info(f"Processed file {file_idx+1}/{len(file_paths)}: {processed_in_file} events from {file_path}")
    logger.info(f"Job {inputs.job_id} completed. Total events processed: {total_processed}")
    return total_processed


@activity.defn
async def update_migration_status_activity(inputs: UpdateMigrationStatusActivityInputs) -> bool:
    """
    Updates the ManagedMigration model status based on workflow state.
    """

    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    logger.info(f"Updating migration status for job {inputs.job_id}")

    try:
        migration = ManagedMigration.objects.get(id=inputs.job_id)
        migration.status = inputs.status

        if inputs.status in [
            ManagedMigration.Status.COMPLETED,
            ManagedMigration.Status.FAILED,
            ManagedMigration.Status.CANCELLED,
        ]:
            migration.finshed_at = dt.datetime.now()
        if inputs.error:
            migration.error = inputs.error
        migration.save()

        logger.info(f"Migration status updated to {inputs.status}")
        return True

    except ManagedMigration.DoesNotExist:
        logger.exception(f"Migration with job_id {inputs.job_id} does not exist")
        return True
    except Exception as e:
        logger.exception(f"Failed to update migration status: {str(e)}")
        return False
