"""
Manual workflow trigger script for batch trace summarization.

This script allows you to manually trigger the batch trace summarization workflow
for testing and development purposes.

Usage:
    # From Django shell:
    python manage.py shell
    >>> from posthog.temporal.llm_analytics.trace_summarization.trigger_workflow import trigger_batch_summarization
    >>> trigger_batch_summarization(team_id=1)

    # Or run directly:
    python manage.py shell < posthog/temporal/llm_analytics/trace_summarization/trigger_workflow.py
"""
# ruff: noqa: T201

import asyncio
from datetime import UTC, datetime

from django.conf import settings

from asgiref.sync import async_to_sync

from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs


def find_teams_with_traces():
    """Find teams that have LLM trace data."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT team_id, COUNT(*) as trace_count
            FROM events
            WHERE event = '$ai_trace'
            GROUP BY team_id
            ORDER BY trace_count DESC
            LIMIT 10
            """
        )
        results = cursor.fetchall()

    if not results:
        print("No teams found with trace data.")
        print("You need to seed your local PostHog with LLM trace data first.")
        return []

    print("\nTeams with trace data:")
    print("=" * 50)
    for team_id, count in results:
        print(f"Team ID: {team_id:4d} | Trace count: {count:6d}")
    print("=" * 50)

    return results


def trigger_batch_summarization(
    team_id: int,
    max_traces: int | None = None,
    batch_size: int | None = None,
    mode: str = "minimal",
    window_minutes: int | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    wait: bool = True,
):
    """
    Trigger batch trace summarization workflow synchronously.

    Args:
        team_id: Team ID to process traces for
        max_traces: Maximum traces to process in window (default: 100)
        batch_size: Batch size for processing (default: 10)
        mode: Summary detail level - "minimal" or "detailed" (default: "minimal")
        window_minutes: Time window to query in minutes (default: 60)
        window_start: Start of explicit time window in RFC3339 format (optional)
        window_end: End of explicit time window in RFC3339 format (optional)
        wait: Wait for workflow to complete (default: True)

    Returns:
        dict: Workflow result if wait=True, WorkflowHandle if wait=False
    """
    client = sync_connect()

    # Build inputs object
    inputs = BatchSummarizationInputs(
        team_id=team_id,
        max_traces=max_traces if max_traces is not None else 100,
        batch_size=batch_size if batch_size is not None else 10,
        mode=mode,
        window_minutes=window_minutes if window_minutes is not None else 60,
        window_start=window_start,
        window_end=window_end,
    )

    workflow_id = f"batch-summarization-team-{team_id}-{datetime.now(UTC).isoformat()}"

    print(f"\n{'='*60}")
    print(f"Triggering batch trace summarization workflow")
    print(f"{'='*60}")
    print(f"Workflow ID: {workflow_id}")
    print(f"Team ID: {team_id}")
    print(f"Max traces: {max_traces or 'default (100)'}")
    print(f"Batch size: {batch_size or 'default (10)'}")
    print(f"Mode: {mode}")
    print(f"Window: {window_minutes or 60} minutes")
    print(f"{'='*60}\n")

    if wait:
        print("⏳ Executing workflow (this may take a while)...\n")
        result = async_to_sync(client.execute_workflow)(
            "batch-trace-summarization",
            inputs,
            id=workflow_id,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        )

        print(f"\n{'='*60}")
        print("✅ Workflow completed!")
        print(f"{'='*60}")
        print(f"Batch run ID: {result.get('batch_run_id', 'N/A')}")
        print(f"Traces queried: {result.get('traces_queried', 0)}")
        print(f"Summaries generated: {result.get('summaries_generated', 0)}")
        print(f"Events emitted: {result.get('events_emitted', 0)}")
        print(f"Duration: {result.get('duration_seconds', 0):.2f}s")
        print(f"{'='*60}\n")

        return result
    else:
        print("🚀 Starting workflow (non-blocking)...\n")
        handle = asyncio.run(
            _start_workflow_async(
                client,
                inputs,
                workflow_id,
            )
        )

        print(f"\n{'='*60}")
        print("✅ Workflow started!")
        print(f"{'='*60}")
        print(f"Workflow ID: {handle.id}")
        print(f"Check status in Temporal UI: http://localhost:8233")
        print(f"{'='*60}\n")

        return handle


async def _start_workflow_async(client, inputs, workflow_id):
    """Helper to start workflow asynchronously."""
    return await client.start_workflow(
        "batch-trace-summarization",
        inputs,
        id=workflow_id,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
    )


async def trigger_batch_summarization_async(
    team_id: int,
    max_traces: int | None = None,
    batch_size: int | None = None,
    mode: str = "minimal",
    window_minutes: int | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
):
    """
    Trigger batch trace summarization workflow asynchronously.

    Same arguments as trigger_batch_summarization() but runs in async context.
    Use this if you're already in an async function.
    """
    client = await async_connect()

    # Build inputs object
    inputs = BatchSummarizationInputs(
        team_id=team_id,
        max_traces=max_traces if max_traces is not None else 100,
        batch_size=batch_size if batch_size is not None else 10,
        mode=mode,
        window_minutes=window_minutes if window_minutes is not None else 60,
        window_start=window_start,
        window_end=window_end,
    )

    workflow_id = f"batch-summarization-team-{team_id}-{datetime.now(UTC).isoformat()}"

    print(f"\n{'='*60}")
    print(f"Triggering batch trace summarization workflow")
    print(f"{'='*60}")
    print(f"Workflow ID: {workflow_id}")
    print(f"Team ID: {team_id}")
    print(f"{'='*60}\n")

    result = await client.execute_workflow(
        "batch-trace-summarization",
        inputs,
        id=workflow_id,
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
    )

    print(f"\n{'='*60}")
    print("✅ Workflow completed!")
    print(f"{'='*60}")
    print(f"Summaries generated: {result.get('summaries_generated', 0)}")
    print(f"Events emitted: {result.get('events_emitted', 0)}")
    print(f"{'='*60}\n")

    return result


# Example usage when running directly
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Batch Trace Summarization - Manual Trigger Script")
    print("=" * 60 + "\n")

    # Find teams with traces
    teams = find_teams_with_traces()

    if teams:
        print("\nExample usage:")
        print("-" * 60)
        team_id = teams[0][0]
        print(f"trigger_batch_summarization(team_id={team_id})")
        print(f"trigger_batch_summarization(team_id={team_id}, max_traces=50)")
        print(f"trigger_batch_summarization(team_id={team_id}, window_minutes=30)")
        print(f"trigger_batch_summarization(team_id={team_id}, mode='detailed')")
        print("-" * 60)

        print("\nRun from Django shell:")
        print("-" * 60)
        print("python manage.py shell")
        print(
            ">>> from posthog.temporal.llm_analytics.trace_summarization.trigger_workflow import trigger_batch_summarization"
        )
        print(f">>> trigger_batch_summarization(team_id={team_id})")
        print("-" * 60)
