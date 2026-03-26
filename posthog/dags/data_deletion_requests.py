import time
from dataclasses import dataclass
from datetime import datetime

import dagster
import pydantic

from posthog.clickhouse.cluster import ClickhouseCluster, LightweightDeleteMutationRunner
from posthog.dags.common import JobOwners
from posthog.models.data_deletion_request import DataDeletionRequest, RequestStatus, RequestType
from posthog.models.event.sql import EVENTS_DATA_TABLE


class DataDeletionRequestConfig(dagster.Config):
    request_id: str = pydantic.Field(description="UUID of the DataDeletionRequest to execute.")


@dataclass
class DeletionRequestContext:
    request_id: str
    team_id: int
    start_time: datetime
    end_time: datetime
    events: list[str]


@dagster.op(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def load_deletion_request(
    context: dagster.OpExecutionContext,
    config: DataDeletionRequestConfig,
) -> DeletionRequestContext:
    """Load and validate the deletion request, transition to IN_PROGRESS."""
    from django.db import transaction

    with transaction.atomic():
        request = (
            DataDeletionRequest.objects.select_for_update()
            .filter(
                pk=config.request_id,
                status=RequestStatus.APPROVED,
                request_type=RequestType.EVENT_REMOVAL,
            )
            .first()
        )

        if not request:
            raise dagster.Failure(
                f"Request {config.request_id} is not an approved event_removal request.",
            )

        request.status = RequestStatus.IN_PROGRESS
        request.save(update_fields=["status", "updated_at"])

    context.log.info(
        f"Processing deletion request {request.pk}: "
        f"team_id={request.team_id}, events={request.events}, "
        f"time_range={request.start_time} to {request.end_time}"
    )
    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(request.team_id),
            "events": dagster.MetadataValue.text(", ".join(request.events)),
            "start_time": dagster.MetadataValue.text(str(request.start_time)),
            "end_time": dagster.MetadataValue.text(str(request.end_time)),
        }
    )

    return DeletionRequestContext(
        request_id=str(request.pk),
        team_id=request.team_id,
        start_time=request.start_time,
        end_time=request.end_time,
        events=request.events,
    )


@dagster.op(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def execute_event_deletion(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    deletion_request: DeletionRequestContext,
) -> DeletionRequestContext:
    """Execute lightweight deletes on each shard serially."""
    table = EVENTS_DATA_TABLE()
    shards = sorted(cluster.shards)
    total_shards = len(shards)

    context.log.info(f"Starting event deletion across {total_shards} shards on table {table}")

    for idx, shard_num in enumerate(shards, 1):
        context.log.info(f"Processing shard {shard_num} ({idx}/{total_shards})")
        shard_start = time.monotonic()

        runner = LightweightDeleteMutationRunner(
            table=table,
            predicate=(
                "team_id = %(team_id)s "
                "AND timestamp >= %(start_time)s "
                "AND timestamp < %(end_time)s "
                "AND event IN %(events)s"
            ),
            parameters={
                "team_id": deletion_request.team_id,
                "start_time": deletion_request.start_time,
                "end_time": deletion_request.end_time,
                "events": deletion_request.events,
            },
            settings={"lightweight_deletes_sync": 0},
        )

        # Run the mutation on one host in this shard
        shard_result = cluster.map_any_host_in_shards({shard_num: runner}).result()
        _host, mutation_waiter = next(iter(shard_result.items()))

        # Wait for the mutation to complete on all replicas in this shard
        cluster.map_all_hosts_in_shard(shard_num, mutation_waiter.wait).result()

        elapsed = time.monotonic() - shard_start
        context.log.info(f"Shard {shard_num} complete in {elapsed:.1f}s")

    context.add_output_metadata(
        {
            "shards_processed": dagster.MetadataValue.int(total_shards),
            "table": dagster.MetadataValue.text(table),
        }
    )

    return deletion_request


@dagster.op(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def mark_deletion_complete(
    context: dagster.OpExecutionContext,
    deletion_request: DeletionRequestContext,
) -> None:
    """Mark the deletion request as completed."""
    from django.utils import timezone

    DataDeletionRequest.objects.filter(
        pk=deletion_request.request_id,
        status=RequestStatus.IN_PROGRESS,
    ).update(status=RequestStatus.COMPLETED, updated_at=timezone.now())

    context.log.info(f"Deletion request {deletion_request.request_id} marked as completed.")


@dagster.failure_hook()
def mark_deletion_failed(context: dagster.HookContext) -> None:
    """Mark the deletion request as failed if any op fails."""
    from django.utils import timezone

    run = context.instance.get_run_by_id(context.run_id)
    if run is None:
        return

    run_config = run.run_config
    if not isinstance(run_config, dict):
        return

    request_id = run_config.get("ops", {}).get("load_deletion_request", {}).get("config", {}).get("request_id")
    if not request_id:
        return

    DataDeletionRequest.objects.filter(
        pk=request_id,
        status=RequestStatus.IN_PROGRESS,
    ).update(status=RequestStatus.FAILED, updated_at=timezone.now())

    context.log.error(f"Deletion request {request_id} marked as failed.")


@dagster.job(
    tags={"owner": JobOwners.TEAM_CLICKHOUSE.value},
    hooks={mark_deletion_failed},
)
def data_deletion_request_event_removal():
    """Execute an approved event deletion request by running lightweight deletes shard by shard."""
    request = load_deletion_request()
    result = execute_event_deletion(request)
    mark_deletion_complete(result)
