"""
Manual trigger helpers for batch trace summarization.

Helper functions for manually triggering the batch trace summarization workflows
for testing, development, and debugging purposes.

Note: The workflow runs automatically every hour via the coordinator. This script
is only needed for manual/ad-hoc testing.

Usage:
    # From Django shell:
    python manage.py shell
    >>> from posthog.temporal.llm_analytics.trace_summarization.manual_trigger import trigger_coordinator, trigger_single_team, find_teams_with_traces

    # Find teams with traces:
    >>> find_teams_with_traces()

    # Trigger coordinator (processes all teams - same as scheduled run):
    >>> trigger_coordinator()

    # Trigger for a specific team only (bypass coordinator):
    >>> trigger_single_team(team_id=1)

    # Or run directly:
    python manage.py shell < posthog/temporal/llm_analytics/trace_summarization/manual_trigger.py
"""
# ruff: noqa: T201

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

from asgiref.sync import async_to_sync

from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.llm_analytics.trace_summarization.constants import WORKFLOW_EXECUTION_TIMEOUT_MINUTES
from posthog.temporal.llm_analytics.trace_summarization.coordinator import BatchTraceSummarizationCoordinatorInputs
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs


def find_teams_with_traces(lookback_hours: int = 24):
    """Find teams that have LLM trace data in the lookback window."""
    from posthog.temporal.llm_analytics.trace_summarization.coordinator import query_teams_with_traces

    team_ids = query_teams_with_traces(lookback_hours)

    if not team_ids:
        print("No teams found with trace data.")
        print("You need to seed your local PostHog with LLM trace data first.")
        return []

    print("\nTeams with trace data:")
    print("=" * 50)
    for team_id in team_ids:
        print(f"Team ID: {team_id:4d}")
    print("=" * 50)
    print(f"Total teams: {len(team_ids)}")

    return team_ids


def trigger_coordinator(
    max_traces: int | None = None,
    batch_size: int | None = None,
    mode: str = "minimal",
    window_minutes: int | None = None,
    model: str | None = None,
    lookback_hours: int | None = None,
    wait: bool = True,
):
    """
    Trigger the coordinator workflow (processes all teams with trace activity).

    This is what runs automatically on the hourly schedule. Use this to test
    the full production flow.

    Args:
        max_traces: Maximum traces to process per team (default: 500)
        batch_size: Batch size for processing (default: 10)
        mode: Summary detail level - "minimal" or "detailed" (default: "minimal")
        window_minutes: Time window to query in minutes (default: 60)
        model: LLM model to use (default: gpt-5-mini for better quality)
        lookback_hours: How far back to look for team activity (default: 24)
        wait: Wait for workflow to complete (default: True)

    Returns:
        dict: Workflow result if wait=True, WorkflowHandle if wait=False
    """
    client = sync_connect()

    inputs = BatchTraceSummarizationCoordinatorInputs(
        max_traces=max_traces if max_traces is not None else 500,
        batch_size=batch_size if batch_size is not None else 10,
        mode=mode,
        window_minutes=window_minutes if window_minutes is not None else 60,
        model=model,
        lookback_hours=lookback_hours if lookback_hours is not None else 24,
    )

    workflow_id = f"batch-summarization-coordinator-{datetime.now(UTC).isoformat()}"

    print(f"\n{'='*60}")
    print("Triggering batch trace summarization coordinator workflow")
    print(f"{'='*60}")
    print(f"Workflow ID: {workflow_id}")
    print(f"Max traces per team: {max_traces or 'default (500)'}")
    print(f"Batch size: {batch_size or 'default (10)'}")
    print(f"Mode: {mode}")
    print(f"Window: {window_minutes or 60} minutes")
    print(f"Model: {model or 'default (gpt-5-mini)'}")
    print(f"Lookback: {lookback_hours or 24} hours")
    print(f"{'='*60}\n")

    if wait:
        print("⏳ Executing coordinator workflow (this may take a while)...\n")

        async def _execute():
            async_client = await async_connect()
            return await async_client.execute_workflow(
                "batch-trace-summarization-coordinator",
                inputs,
                id=workflow_id,
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                execution_timeout=timedelta(hours=2),
            )

        result: dict[str, Any] = async_to_sync(_execute)()

        print(f"\n{'='*60}")
        print("✅ Coordinator workflow completed!")
        print(f"{'='*60}")
        print(f"Teams processed: {result.get('teams_processed', 0)}")
        print(f"Teams failed: {result.get('teams_failed', 0)}")
        print(f"Total traces queried: {result.get('total_traces', 0)}")
        print(f"Total summaries generated: {result.get('total_summaries', 0)}")
        print(f"{'='*60}\n")

        return result
    else:
        print("🚀 Starting coordinator workflow (non-blocking)...\n")
        handle = asyncio.run(
            _start_workflow_async(
                client,
                inputs,
                workflow_id,
                "batch-trace-summarization-coordinator",
            )
        )

        print(f"\n{'='*60}")
        print("✅ Coordinator workflow started!")
        print(f"{'='*60}")
        print(f"Workflow ID: {handle.id}")
        print(f"Check status in Temporal UI: http://localhost:8233")
        print(f"{'='*60}\n")

        return handle


def trigger_single_team(
    team_id: int,
    max_traces: int | None = None,
    batch_size: int | None = None,
    mode: str = "minimal",
    window_minutes: int | None = None,
    model: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    wait: bool = True,
):
    """
    Trigger batch trace summarization for a single team (bypasses coordinator).

    Use this for testing a specific team or debugging. For production-like
    testing, use trigger_coordinator() instead.

    Args:
        team_id: Team ID to process traces for
        max_traces: Maximum traces to process in window (default: 500)
        batch_size: Batch size for processing (default: 10)
        mode: Summary detail level - "minimal" or "detailed" (default: "minimal")
        window_minutes: Time window to query in minutes (default: 60)
        model: LLM model to use (default: gpt-5-mini for better quality)
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
        max_traces=max_traces if max_traces is not None else 500,
        batch_size=batch_size if batch_size is not None else 10,
        mode=mode,
        window_minutes=window_minutes if window_minutes is not None else 60,
        model=model,
        window_start=window_start,
        window_end=window_end,
    )

    workflow_id = f"batch-summarization-team-{team_id}-{datetime.now(UTC).isoformat()}"

    print(f"\n{'='*60}")
    print(f"Triggering batch trace summarization workflow")
    print(f"{'='*60}")
    print(f"Workflow ID: {workflow_id}")
    print(f"Team ID: {team_id}")
    print(f"Max traces: {max_traces or 'default (500)'}")
    print(f"Batch size: {batch_size or 'default (10)'}")
    print(f"Mode: {mode}")
    print(f"Window: {window_minutes or 60} minutes")
    print(f"Model: {model or 'default (gpt-5-mini)'}")
    print(f"{'='*60}\n")

    if wait:
        print("⏳ Executing workflow (this may take a while)...\n")

        async def _execute():
            async_client = await async_connect()
            return await async_client.execute_workflow(
                "batch-trace-summarization",
                inputs,
                id=workflow_id,
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                execution_timeout=timedelta(minutes=WORKFLOW_EXECUTION_TIMEOUT_MINUTES),
            )

        result: dict[str, Any] = async_to_sync(_execute)()

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
                "batch-trace-summarization",
            )
        )

        print(f"\n{'='*60}")
        print("✅ Workflow started!")
        print(f"{'='*60}")
        print(f"Workflow ID: {handle.id}")
        print(f"Check status in Temporal UI: http://localhost:8233")
        print(f"{'='*60}\n")

        return handle


async def _start_workflow_async(client, inputs, workflow_id, workflow_name):
    """Helper to start workflow asynchronously."""
    return await client.start_workflow(
        workflow_name,
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
    model: str | None = None,
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
        max_traces=max_traces if max_traces is not None else 500,
        batch_size=batch_size if batch_size is not None else 10,
        mode=mode,
        window_minutes=window_minutes if window_minutes is not None else 60,
        model=model,
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
        execution_timeout=timedelta(minutes=WORKFLOW_EXECUTION_TIMEOUT_MINUTES),
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
        print("# Trigger coordinator (processes all teams - same as scheduled run):")
        print("trigger_coordinator()")
        print("trigger_coordinator(max_traces=100)")
        print("trigger_coordinator(mode='detailed')")
        print()
        print("# Trigger single team (bypass coordinator):")
        print(f"trigger_single_team(team_id={team_id})")
        print(f"trigger_single_team(team_id={team_id}, max_traces=50)")
        print(f"trigger_single_team(team_id={team_id}, model='gpt-5-mini')")
        print("-" * 60)

        print("\nRun from Django shell:")
        print("-" * 60)
        print("python manage.py shell")
        print(
            ">>> from posthog.temporal.llm_analytics.trace_summarization.manual_trigger import trigger_coordinator, trigger_single_team"
        )
        print(">>> trigger_coordinator()  # Process all teams")
        print(f">>> trigger_single_team(team_id={team_id})  # Process one team")
        print("-" * 60)
