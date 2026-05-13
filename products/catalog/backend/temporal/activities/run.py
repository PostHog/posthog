"""Lifecycle activities for the catalog traversal workflow.

Each run of `CatalogTraversalWorkflow` writes one `CatalogTraversalRun` row to
Postgres tracking the pass's status, timing, and counters. The workflow calls
`create_traversal_run` first, then `complete_traversal_run` on success or
`fail_traversal_run` on exception. Subsequent commits add enumerate / upsert /
propose activities between these bookends.

Activities are `async def` so the worker (asyncio-based) can interleave many
runs; the Postgres I/O is offloaded to a thread via `asyncio.to_thread` so it
doesn't block the event loop.
"""

import asyncio
from dataclasses import dataclass, field

from django.utils import timezone

from temporalio import activity

from products.catalog.backend.models import CatalogTraversalRun


@dataclass
class TraversalCounts:
    nodes: int = 0
    columns: int = 0
    relationships: int = 0
    descriptions: int = 0


@dataclass
class CreateRunArgs:
    team_id: int
    trigger: str  # CatalogTraversalRun.Trigger value: "cron" | "manual" | "api"
    generator_model: str | None = None


@dataclass
class CompleteRunArgs:
    run_id: str
    counts: TraversalCounts = field(default_factory=TraversalCounts)


@dataclass
class FailRunArgs:
    run_id: str
    error: str


@activity.defn
async def create_traversal_run(args: CreateRunArgs) -> str:
    """Insert a new CatalogTraversalRun row, mark it running, return its id."""
    return await asyncio.to_thread(_create_traversal_run_sync, args)


@activity.defn
async def complete_traversal_run(args: CompleteRunArgs) -> None:
    """Mark the run completed and write final counters."""
    await asyncio.to_thread(_complete_traversal_run_sync, args)


@activity.defn
async def fail_traversal_run(args: FailRunArgs) -> None:
    """Mark the run failed with an error message."""
    await asyncio.to_thread(_fail_traversal_run_sync, args)


def _create_traversal_run_sync(args: CreateRunArgs) -> str:
    run = CatalogTraversalRun.objects.create(
        team_id=args.team_id,
        trigger=args.trigger,
        status=CatalogTraversalRun.Status.RUNNING,
        started_at=timezone.now(),
        generator_model=args.generator_model,
    )
    return str(run.id)


def _complete_traversal_run_sync(args: CompleteRunArgs) -> None:
    CatalogTraversalRun.objects.filter(id=args.run_id).update(
        status=CatalogTraversalRun.Status.COMPLETED,
        completed_at=timezone.now(),
        nodes_processed=args.counts.nodes,
        columns_processed=args.counts.columns,
        relationships_proposed=args.counts.relationships,
        descriptions_generated=args.counts.descriptions,
    )


def _fail_traversal_run_sync(args: FailRunArgs) -> None:
    # Truncate the error to fit Django's TextField sanely — long stack traces
    # otherwise bloat the row and slow down admin listings.
    CatalogTraversalRun.objects.filter(id=args.run_id).update(
        status=CatalogTraversalRun.Status.FAILED,
        completed_at=timezone.now(),
        error=args.error[:8000],
    )
