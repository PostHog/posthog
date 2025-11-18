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

from posthog.temporal.common.client import async_connect, sync_connect


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
    sample_size: int | None = None,
    batch_size: int | None = None,
    mode: str = "minimal",
    start_date: str | None = None,
    end_date: str | None = None,
    wait: bool = True,
):
    """
    Trigger batch trace summarization workflow synchronously.

    Args:
        team_id: Team ID to process traces for
        sample_size: Number of traces to sample (default: 1000)
        batch_size: Batch size for processing (default: 100)
        mode: Summary detail level - "minimal" or "detailed" (default: "minimal")
        start_date: Start of date range in RFC3339 format (optional)
        end_date: End of date range in RFC3339 format (optional)
        wait: Wait for workflow to complete (default: True)

    Returns:
        dict: Workflow result if wait=True, WorkflowHandle if wait=False
    """
    client = sync_connect()

    # Build arguments list
    args = [str(team_id)]
    if sample_size is not None:
        args.append(str(sample_size))
    if batch_size is not None:
        args.append(str(batch_size))
    if mode != "minimal":
        args.append(mode)
    if start_date:
        args.append(start_date)
    if end_date:
        args.append(end_date)

    workflow_id = f"batch-summarization-team-{team_id}-{datetime.now(UTC).isoformat()}"

    print(f"\n{'='*60}")
    print(f"Triggering batch trace summarization workflow")
    print(f"{'='*60}")
    print(f"Workflow ID: {workflow_id}")
    print(f"Team ID: {team_id}")
    print(f"Sample size: {sample_size or 'default (1000)'}")
    print(f"Batch size: {batch_size or 'default (100)'}")
    print(f"Mode: {mode}")
    print(f"{'='*60}\n")

    if wait:
        print("⏳ Executing workflow (this may take a while)...\n")
        result = client.execute_workflow(
            "batch-trace-summarization",
            args,
            id=workflow_id,
            task_queue="llm-analytics-queue",
        )

        print(f"\n{'='*60}")
        print("✅ Workflow completed!")
        print(f"{'='*60}")
        print(f"Batch run ID: {result.get('batch_run_id', 'N/A')}")
        print(f"Traces sampled: {result.get('traces_sampled', 0)}")
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
                args,
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


async def _start_workflow_async(client, args, workflow_id):
    """Helper to start workflow asynchronously."""
    return await client.start_workflow(
        "batch-trace-summarization",
        args,
        id=workflow_id,
        task_queue="llm-analytics-queue",
    )


async def trigger_batch_summarization_async(
    team_id: int,
    sample_size: int | None = None,
    batch_size: int | None = None,
    mode: str = "minimal",
    start_date: str | None = None,
    end_date: str | None = None,
):
    """
    Trigger batch trace summarization workflow asynchronously.

    Same arguments as trigger_batch_summarization() but runs in async context.
    Use this if you're already in an async function.
    """
    client = await async_connect()

    # Build arguments list
    args = [str(team_id)]
    if sample_size is not None:
        args.append(str(sample_size))
    if batch_size is not None:
        args.append(str(batch_size))
    if mode != "minimal":
        args.append(mode)
    if start_date:
        args.append(start_date)
    if end_date:
        args.append(end_date)

    workflow_id = f"batch-summarization-team-{team_id}-{datetime.now(UTC).isoformat()}"

    print(f"\n{'='*60}")
    print(f"Triggering batch trace summarization workflow")
    print(f"{'='*60}")
    print(f"Workflow ID: {workflow_id}")
    print(f"Team ID: {team_id}")
    print(f"{'='*60}\n")

    result = await client.execute_workflow(
        "batch-trace-summarization",
        args,
        id=workflow_id,
        task_queue="llm-analytics-queue",
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
        print(f"trigger_batch_summarization(team_id={team_id}, sample_size=500)")
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
