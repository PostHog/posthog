"""Test utilities to manipulate BatchExport* models."""
import uuid

import temporalio.client
from asgiref.sync import sync_to_async

from posthog.batch_exports.models import (
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportRun,
)
from posthog.batch_exports.service import sync_batch_export


def create_batch_export(team_id: int, interval: str, name: str, destination_data: dict) -> BatchExport:
    """Create a BatchExport and its underlying Schedule."""

    destination = BatchExportDestination(**destination_data)
    batch_export = BatchExport(team_id=team_id, destination=destination, interval=interval, name=name)

    sync_batch_export(batch_export, created=True)

    destination.save()
    batch_export.save()

    return batch_export


async def acreate_batch_export(team_id: int, interval: str, name: str, destination_data: dict) -> BatchExport:
    """Async create a BatchExport and its underlying Schedule."""
    return await sync_to_async(create_batch_export)(team_id, interval, name, destination_data)  # type: ignore


async def adelete_batch_export(batch_export: BatchExport, temporal_client: temporalio.client.Client) -> None:
    """Async delete a BatchExport and its underlying Schedule."""
    handle = temporal_client.get_schedule_handle(str(batch_export.id))

    try:
        await handle.delete()
    except temporalio.service.RPCError:
        # This means the schedule was already deleted, so we can continue
        pass

    await sync_to_async(batch_export.delete)()  # type: ignore


def fetch_batch_export_runs(batch_export_id: uuid.UUID, limit: int = 100) -> list[BatchExportRun]:
    """Fetch the BatchExportRuns for a given BatchExport."""
    return list(BatchExportRun.objects.filter(batch_export_id=batch_export_id).order_by("-created_at")[:limit])


async def afetch_batch_export_runs(batch_export_id: uuid.UUID, limit: int = 100) -> list[BatchExportRun]:
    """Async fetch the BatchExportRuns for a given BatchExport."""
    return await sync_to_async(fetch_batch_export_runs)(batch_export_id, limit)  # type: ignore


def fetch_batch_export_backfills(batch_export_id: uuid.UUID, limit: int = 100) -> list[BatchExportBackfill]:
    """Fetch the BatchExportBackfills for a given BatchExport."""
    return list(BatchExportBackfill.objects.filter(batch_export_id=batch_export_id).order_by("-created_at")[:limit])


async def afetch_batch_export_backfills(batch_export_id: uuid.UUID, limit: int = 100) -> list[BatchExportBackfill]:
    """Fetch the BatchExportBackfills for a given BatchExport."""
    return await sync_to_async(fetch_batch_export_backfills)(batch_export_id, limit)  # type: ignore
