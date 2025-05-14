import json
import os
import datetime as dt
import typing
import dataclasses
from pathlib import Path
import requests

import structlog
from django.db import close_old_connections
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync


@dataclasses.dataclass
class ExternalEventWorkflowInputs:
    team_id: int
    amplitude_api_key: str
    posthog_api_key: str
    job_id: str = None
    start_date: str = None
    end_date: str = None


@workflow.defn(name="external-event-job")
class ExternalEventJobWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExternalEventWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ExternalEventWorkflowInputs(**loaded)
    
    @workflow.run
    async def run(self, inputs: ExternalEventWorkflowInputs):
        # set up the temp file paths, TODO: add the date to temp dir when we have it
        temp_dir = f"/tmp/posthog/amplitude_import/{inputs.team_id}/{inputs.job_id}"
        compressed_file_path = f"{temp_dir}/amplitude_import.json.gz"
        uncompressed_file_path = f"{temp_dir}/amplitude_data.json"

        # TODO: define job status stuff at some point
        update_inputs = JobStatusUpdateInputs(
            job_id=inputs.job_id,
            team_id=inputs.team_id,
            status="RUNNING",
        )

        try:
            await workflow.execute_activity(
                udpate_job_status,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # figure out the way to manage the start, end date progress
            fetch_inputs = FetchAmplitudeDataActivityInputs(
                api_key=inputs.api_key,
                start_date=inputs.start_date,
                end_date=inputs.end_date,
                file_path=compressed_file_path,
            )

            compressed_file = await workflow.execute_activity(
                fetch_amplitude_data_activity,
                fetch_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                # TODO: Figure out retry policy
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # potentially update progress
            # update_inputs.progress = 0.3
            # workflow update job statu ->

            uncompress_inputs = UncompressAmplitudeDataActivityInputs(
                file_path=compressed_file_path,
                uncompressed_file_path=uncompressed_file_path,
            )

            await workflow.execute_activity(
                uncompress_amplitude_data_activity,
                uncompress_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                # TODO: Figure out retry policy
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # create inputs for the processing events activity
            process_inputs = ProcessEventsActivityInputs(
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                file_path=uncompressed_file,
                posthog_api_key=inputs.posthog_api_key,
                batch_size=20,
            )

            total_events = await worfklow.execute_activity(
                process_events_activity,
                process_inputs,
                start_to_close_timeout=dt.timedelta(hours=12),
                heartbeat_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_interval=dt.timedelta(seconds=60), maximum_attempts=3),
            )

            # update status input
            update_inputs.status = "COMPLETED"
            update_inputs.progress = 1.0

        except exceptions.ActivityError as e:
            update_inputs.status = "FAILED"
            update_inputs.internal_error = str(e.cause)
            update_inputs.latest_error = str(e.cause)
            raise
        except Exception as e:
            update_inputs.status = "FAILED"
            update_inputs.latest_error = str(e)
            update_inputs.latest_error = "An unexpected error has occurred"
            raise
        finally:
            # Clean up temp files
            try:
                import shutil
                shutil.rmtree(temp_dir)
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass

            await worfklow.execute_activity(
                update_job_status,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=3,
                ),
            )


@activity.defn
async def fetch_amplitude_data_activity(inputs: FetchAmplitudeDataActivityInputs) -> str:
    """
    Fetches data from Amplitude API and saves it to a file.
    Returns the path to the file.
    """
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    logger.info(f"Fetching Amplitude data for job {inputs.job_id}")

    url = "https://amplitude.com/api/2/export"

    ## NICKS TODO: understand secret key?
    auth = (inputs.api_key, inputs.secret_key)

    params = {
        'start': inputs.start_date,
        'end': inputs.end_date,
    }

    # NICKS TODO: add support for event_type filtering
    if input.event_types:
        params['event_type'] = ','.join(input.event_types)

    # NICKS TODO: understand stream=True
    response = requests.get(url, auth=auth, params=params, stream=True)

    if response.status_code == 200:
        with open(inputs.file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
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

    extract_dir = inputs.uncompressed_file_path
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(inputs.file_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)

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
    with open(inputs.file_path, 'r') as f:
        batch = []
        for i, line in enumerate(f):
            ph_event = parse_amplitude_event(line.strip())
            batch.append(ph_event)


            # NICKS TODO: handle case where the file doesnt have enouhg events left for batch size
            if len(batch) >= inputs.batch_size or i == total_processed - 1:
                logger.info(f"Sending batch of {len(batch)} events to PostHog")
                url = f"{inputs.posthog_domain}/batch/"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "api_key": inputs.posthog_api_key,
                    "historical_migration": True,
                    "batch": batch
                }
                # NICKS TODO: handle errors
                response = requests.post(url, headers=headers, json=payload)
                total_processed += len(batch)
                batch = []

    return total_processed




