#!/usr/bin/env python3
# ruff: noqa: T201 - CLI script uses print for output
"""
Extract failed team IDs from person property reconciliation job runs via Dagster Cloud GraphQL API.

Usage:
    export DAGSTER_CLOUD_TOKEN="<USER_TOKEN>"
    python posthog/dags/scripts/extract_reconciliation_results.py \
        --org posthog \
        --deployment <prod-us | prod-eu> \
        [--all | --limit <INT> | --since "2026-01-01" --until "2026-01-12"]

Prerequisites:
    1. Get a Dagster Cloud user token:
       - Go to Dagster Cloud UI (e.g., https://posthog.dagster.cloud/)
       - Click your avatar (top-right) > "Organization settings" > "Tokens" tab
       - Create a User Token and copy it
       - REMEMBER: revoke the token when you're done!
    2. Set the DAGSTER_CLOUD_TOKEN environment variable
"""

import os
import ast
import csv
import sys
import json
import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

# GraphQL query to get runs for the reconciliation job
RUNS_QUERY = """
query GetRuns($limit: Int!, $cursor: String, $filter: RunsFilter!) {
  runsOrError(filter: $filter, limit: $limit, cursor: $cursor) {
    __typename
    ... on Runs {
      results {
        runId
        status
        startTime
        endTime
        tags {
          key
          value
        }
      }
    }
    ... on InvalidPipelineRunsFilterError {
      message
    }
    ... on PythonError {
      message
      stack
    }
  }
}
"""

# GraphQL query to get a single run by ID
RUN_QUERY = """
query GetRun($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run {
      runId
      status
      startTime
      endTime
      tags {
        key
        value
      }
    }
    ... on RunNotFoundError {
      message
    }
    ... on PythonError {
      message
      stack
    }
  }
}
"""

# GraphQL query to get step output events for a run
STEP_OUTPUTS_QUERY = """
query GetStepOutputs($runId: ID!) {
  logsForRun(runId: $runId) {
    __typename
    ... on EventConnection {
      events {
        __typename
        ... on ExecutionStepOutputEvent {
          stepKey
          metadataEntries {
            __typename
            label
            ... on TextMetadataEntry {
              text
            }
            ... on JsonMetadataEntry {
              jsonString
            }
            ... on IntMetadataEntry {
              intValue
            }
          }
        }
      }
    }
    ... on PythonError {
      message
      stack
    }
  }
}
"""


@dataclass
class TeamResult:
    """Result for a single team from a reconciliation run."""

    team_id: int
    status: str
    persons_processed: int
    persons_updated: int
    persons_skipped: int
    error: str | None
    run_id: str
    step_key: str


@dataclass
class RunSummary:
    """Summary of a single reconciliation job run."""

    run_id: str
    status: str
    start_time: datetime | None
    end_time: datetime | None
    team_range: str | None
    teams_count: int
    teams_succeeded: int
    teams_failed: int
    failed_team_ids: list[int]
    team_results: list[TeamResult]
    persons_processed: int
    persons_updated: int
    persons_skipped: int


class DagsterCloudClient:
    """Client for Dagster Cloud GraphQL API."""

    def __init__(self, org: str, deployment: str, token: str):
        self.base_url = f"https://{org}.dagster.cloud/{deployment}/graphql"
        self.headers = {
            "Dagster-Cloud-Api-Token": token,
            "Content-Type": "application/json",
        }

    def _execute_query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query and return the result."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=60)
        response.raise_for_status()

        result = response.json()
        if "errors" in result:
            raise RuntimeError(f"GraphQL errors: {result['errors']}")

        return result["data"]

    def get_runs(
        self,
        job_name: str = "person_property_reconciliation_job",
        statuses: list[str] | None = None,
        created_after: float | None = None,
        created_before: float | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Get runs for the specified job.

        Args:
            job_name: Name of the Dagster job
            statuses: Filter by run statuses
            created_after: Unix timestamp - only return runs created after this time
            created_before: Unix timestamp - only return runs created before this time
            limit: Max runs to return per page
            cursor: Pagination cursor

        Returns:
            Tuple of (runs list, next cursor for pagination)
        """
        run_filter: dict[str, Any] = {"pipelineName": job_name}
        if statuses:
            run_filter["statuses"] = statuses
        if created_after is not None:
            # Dagster API uses "updatedAfter" (no "createdAfter" exists)
            run_filter["updatedAfter"] = created_after
        if created_before is not None:
            run_filter["createdBefore"] = created_before

        variables = {
            "filter": run_filter,
            "limit": limit,
            "cursor": cursor,
        }

        data = self._execute_query(RUNS_QUERY, variables)
        runs_result = data["runsOrError"]

        if runs_result["__typename"] == "Runs":
            results = runs_result["results"]
            # Get cursor for next page (last run's runId if we got a full page)
            next_cursor = results[-1]["runId"] if len(results) == limit else None
            return results, next_cursor
        elif runs_result["__typename"] == "InvalidPipelineRunsFilterError":
            raise RuntimeError(f"Invalid filter: {runs_result['message']}")
        else:
            raise RuntimeError(f"Query error: {runs_result.get('message', 'Unknown error')}")

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get a single run by ID. Returns None if not found."""
        data = self._execute_query(RUN_QUERY, {"runId": run_id})
        result = data["runOrError"]

        if result["__typename"] == "Run":
            return result
        elif result["__typename"] == "RunNotFoundError":
            return None
        else:
            raise RuntimeError(f"Query error: {result.get('message', 'Unknown error')}")

    def get_step_outputs(self, run_id: str) -> list[dict[str, Any]]:
        """Get step output events for a run, filtered to reconcile_team_chunk steps."""
        data = self._execute_query(STEP_OUTPUTS_QUERY, {"runId": run_id})
        logs_result = data["logsForRun"]

        if logs_result["__typename"] == "PythonError":
            raise RuntimeError(f"Query error: {logs_result.get('message', 'Unknown error')}")

        events = logs_result.get("events", [])

        # Filter to only ExecutionStepOutputEvent for reconcile_team_chunk steps
        step_outputs = []
        for event in events:
            if event["__typename"] == "ExecutionStepOutputEvent":
                step_key = event.get("stepKey", "")
                # Match reconcile_team_chunk steps (they have dynamic suffixes like [teams_1_100])
                if "reconcile_team_chunk" in step_key:
                    step_outputs.append(event)

        return step_outputs


def parse_metadata_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse metadata entries into a dictionary."""
    result: dict[str, Any] = {}
    for entry in entries:
        label = entry.get("label", "")
        typename = entry.get("__typename", "")

        if typename == "TextMetadataEntry":
            result[label] = entry.get("text", "")
        elif typename == "JsonMetadataEntry":
            json_str = entry.get("jsonString", "")
            try:
                result[label] = json.loads(json_str) if json_str else None
            except json.JSONDecodeError:
                result[label] = json_str
        elif typename == "IntMetadataEntry":
            result[label] = entry.get("intValue")

    return result


def parse_failed_team_ids(failed_team_ids_str: str) -> list[int]:
    """Parse the failed_team_ids string (Python list repr) into a list of ints."""
    if not failed_team_ids_str or failed_team_ids_str == "[]":
        return []

    try:
        # The string is a Python list repr like "[123, 456, 789]"
        parsed = ast.literal_eval(failed_team_ids_str)
        if isinstance(parsed, list):
            return [int(x) for x in parsed]
    except (ValueError, SyntaxError):
        pass

    return []


def extract_run_results(client: DagsterCloudClient, run: dict[str, Any]) -> RunSummary:
    """Extract results from a single run."""
    run_id = run["runId"]
    status = run["status"]

    # Parse timestamps
    start_time = None
    end_time = None
    if run.get("startTime"):
        start_time = datetime.fromtimestamp(run["startTime"])
    if run.get("endTime"):
        end_time = datetime.fromtimestamp(run["endTime"])

    # Extract team range from tags
    team_range = None
    for tag in run.get("tags", []):
        if tag["key"] == "reconciliation_range":
            team_range = tag["value"]
            break

    # Get step outputs
    step_outputs = client.get_step_outputs(run_id)

    all_failed_team_ids: list[int] = []
    all_team_results: list[TeamResult] = []
    total_teams_count = 0
    total_teams_succeeded = 0
    total_teams_failed = 0
    total_persons_processed = 0
    total_persons_updated = 0
    total_persons_skipped = 0

    for step_output in step_outputs:
        step_key = step_output.get("stepKey", "")
        metadata = parse_metadata_entries(step_output.get("metadataEntries", []))

        # Aggregate counts
        total_teams_count += metadata.get("teams_count", 0) or 0
        total_teams_succeeded += metadata.get("teams_succeeded", 0) or 0
        total_teams_failed += metadata.get("teams_failed", 0) or 0

        # Parse failed team IDs
        failed_ids_str = metadata.get("failed_team_ids", "[]")
        failed_ids = parse_failed_team_ids(failed_ids_str)
        all_failed_team_ids.extend(failed_ids)

        # Parse detailed team results
        teams_results = metadata.get("teams_results", [])
        if isinstance(teams_results, list):
            for team_result in teams_results:
                if isinstance(team_result, dict):
                    persons_processed = team_result.get("persons_processed", 0) or 0
                    persons_updated = team_result.get("persons_updated", 0) or 0
                    persons_skipped = team_result.get("persons_skipped", 0) or 0

                    total_persons_processed += persons_processed
                    total_persons_updated += persons_updated
                    total_persons_skipped += persons_skipped

                    all_team_results.append(
                        TeamResult(
                            team_id=team_result.get("team_id", 0),
                            status=team_result.get("status", "unknown"),
                            persons_processed=persons_processed,
                            persons_updated=persons_updated,
                            persons_skipped=persons_skipped,
                            error=team_result.get("error"),
                            run_id=run_id,
                            step_key=step_key,
                        )
                    )

    return RunSummary(
        run_id=run_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        team_range=team_range,
        teams_count=total_teams_count,
        teams_succeeded=total_teams_succeeded,
        teams_failed=total_teams_failed,
        failed_team_ids=sorted(set(all_failed_team_ids)),
        team_results=all_team_results,
        persons_processed=total_persons_processed,
        persons_updated=total_persons_updated,
        persons_skipped=total_persons_skipped,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Extract failed team IDs from person property reconciliation job runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--org", required=True, help="Dagster Cloud organization name (e.g., 'posthog')")
    parser.add_argument("--deployment", required=True, help="Dagster Cloud deployment name (e.g., 'prod')")
    parser.add_argument(
        "--token",
        default=os.environ.get("DAGSTER_CLOUD_TOKEN"),
        help="Dagster Cloud API token (defaults to DAGSTER_CLOUD_TOKEN env var)",
    )
    parser.add_argument(
        "--status",
        nargs="*",
        choices=["QUEUED", "NOT_STARTED", "STARTING", "STARTED", "SUCCESS", "FAILURE", "CANCELING", "CANCELED"],
        help="Filter runs by status (default: all statuses)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of runs to fetch (default: 100, use --all for unlimited)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="fetch_all",
        help="Fetch ALL runs (ignores --limit)",
    )
    parser.add_argument(
        "--since",
        help="Only include runs created after this date/time in local timezone (format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
    )
    parser.add_argument(
        "--until",
        help="Only include runs created before this date/time in local timezone (format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
    )
    parser.add_argument(
        "--run-id",
        help="Extract results from a specific run ID only",
    )
    parser.add_argument(
        "--output-csv",
        help="Output failed teams to a CSV file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output including per-team results",
    )

    args = parser.parse_args()

    if not args.token:
        print("Error: DAGSTER_CLOUD_TOKEN environment variable not set and --token not provided", file=sys.stderr)
        print("\nTo get a token:", file=sys.stderr)
        print("  1. Go to Dagster Cloud UI (e.g., https://posthog.dagster.cloud/)", file=sys.stderr)
        print("  2. Click your avatar (top-right) > 'Organization settings' > 'Tokens' tab", file=sys.stderr)
        print("  3. Create and copy the token", file=sys.stderr)
        sys.exit(1)

    client = DagsterCloudClient(args.org, args.deployment, args.token)

    def parse_date_arg(value: str, arg_name: str, end_of_day: bool = False) -> float:
        """Parse a date string to unix timestamp. Assumes input is in local timezone."""
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(value, fmt)
                if end_of_day and fmt == "%Y-%m-%d":
                    dt = dt.replace(hour=23, minute=59, second=59)
                return dt.timestamp()
            except ValueError:
                continue
        print(f"Error: Invalid {arg_name} date format: {value}", file=sys.stderr)
        print("Use ISO format: YYYY-MM-DD or YYYY-MM-DD HH:MM:SS", file=sys.stderr)
        sys.exit(1)

    created_after = parse_date_arg(args.since, "--since") if args.since else None
    created_before = parse_date_arg(args.until, "--until", end_of_day=True) if args.until else None

    all_summaries: list[RunSummary] = []
    all_team_results_by_id: dict[int, TeamResult] = {}

    if args.run_id:
        print(f"Fetching results for run {args.run_id}...")
        run = client.get_run(args.run_id)
        if not run:
            print(f"Error: Run {args.run_id} not found", file=sys.stderr)
            sys.exit(1)
        runs_to_process = [run]
    else:
        # Fetch runs with pagination
        filter_info = []
        if args.since:
            filter_info.append(f"since {args.since}")
        if args.until:
            filter_info.append(f"until {args.until}")
        if args.status:
            filter_info.append(f"status={args.status}")
        filter_str = f" ({', '.join(filter_info)})" if filter_info else ""

        limit_str = "all" if args.fetch_all else str(args.limit)
        print(f"Fetching {limit_str} runs for person_property_reconciliation_job{filter_str}...")

        runs_to_process = []
        cursor = None
        max_runs = float("inf") if args.fetch_all else args.limit

        while len(runs_to_process) < max_runs:
            batch_limit = 100 if args.fetch_all else min(100, int(max_runs) - len(runs_to_process))
            runs, cursor = client.get_runs(
                statuses=args.status,
                created_after=created_after,
                created_before=created_before,
                limit=batch_limit,
                cursor=cursor,
            )
            runs_to_process.extend(runs)
            print(f"  Fetched {len(runs_to_process)} runs so far...")
            if not cursor or len(runs) == 0:
                break

        print(f"Found {len(runs_to_process)} runs total")

    # Sort runs by start time (newest first) so we process most recent results first
    runs_to_process.sort(key=lambda r: r.get("startTime") or 0, reverse=True)

    # Process each run
    for i, run in enumerate(runs_to_process, 1):
        run_id = run["runId"]
        print(f"Processing run {i}/{len(runs_to_process)}: {run_id} ({run['status']})...")

        try:
            summary = extract_run_results(client, run)
            all_summaries.append(summary)

            # Collect team results, keeping only the first (most recent) result per team
            for result in summary.team_results:
                if result.team_id not in all_team_results_by_id:
                    all_team_results_by_id[result.team_id] = result

        except Exception as e:
            print(f"  Error processing run {run_id}: {e}", file=sys.stderr)

    # Compute deduplicated aggregates (most recent result per team)
    deduped_results = list(all_team_results_by_id.values())
    deduped_teams_count = len(deduped_results)
    deduped_teams_succeeded = sum(1 for r in deduped_results if r.status == "success")
    deduped_teams_failed = sum(1 for r in deduped_results if r.status == "failed")
    deduped_persons_processed = sum(r.persons_processed for r in deduped_results)
    deduped_persons_updated = sum(r.persons_updated for r in deduped_results)
    deduped_persons_skipped = sum(r.persons_skipped for r in deduped_results)
    deduped_failed_team_ids = sorted(r.team_id for r in deduped_results if r.status == "failed")

    # Compute raw totals (includes retries)
    raw_teams_count = sum(s.teams_count for s in all_summaries)

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY (deduplicated by team - most recent run per team)")
    print("=" * 80)

    print(f"Unique teams processed: {deduped_teams_count}")
    print(f"Teams succeeded: {deduped_teams_succeeded}")
    print(f"Teams failed: {deduped_teams_failed}")
    print(f"Persons processed: {deduped_persons_processed}")
    print(f"Persons updated: {deduped_persons_updated}")
    print(f"Persons skipped: {deduped_persons_skipped}")

    if deduped_failed_team_ids:
        print(f"\nFailed team IDs: {deduped_failed_team_ids}")

    print("\n" + "-" * 80)
    print("RAW TOTALS (all runs, includes retries)")
    print("-" * 80)
    print(f"Runs analyzed: {len(all_summaries)}")
    print(f"Raw team count: {raw_teams_count}")

    # Per-run breakdown
    if args.verbose and all_summaries:
        print("\n" + "-" * 80)
        print("PER-RUN BREAKDOWN")
        print("-" * 80)

        for summary in all_summaries:
            start_str = summary.start_time.strftime("%Y-%m-%d %H:%M:%S") if summary.start_time else "N/A"
            print(f"\nRun: {summary.run_id}")
            print(f"  Status: {summary.status}")
            print(f"  Started: {start_str}")
            print(f"  Team range: {summary.team_range or 'N/A'}")
            print(
                f"  Teams: {summary.teams_count} total, {summary.teams_succeeded} succeeded, {summary.teams_failed} failed"
            )
            print(
                f"  Persons: {summary.persons_processed} processed, {summary.persons_updated} updated, {summary.persons_skipped} skipped"
            )

            if summary.failed_team_ids:
                print(f"  Failed team IDs: {summary.failed_team_ids}")

    # Show error details for failed teams (from deduplicated results)
    failed_team_results = [r for r in deduped_results if r.status == "failed"]
    if args.verbose and failed_team_results:
        print("\n" + "-" * 80)
        print("FAILED TEAM DETAILS")
        print("-" * 80)

        for result in failed_team_results:
            print(f"\nTeam {result.team_id}:")
            print(f"  Run: {result.run_id}")
            print(f"  Step: {result.step_key}")
            print(f"  Error: {result.error or 'No error message'}")

    # Export to CSV if requested (uses deduplicated results)
    if args.output_csv and failed_team_results:
        print(f"\nWriting failed teams to {args.output_csv}...")
        with open(args.output_csv, "w", newline="") as csvfile:
            writer = csv.DictWriter(
                csvfile,
                fieldnames=[
                    "team_id",
                    "status",
                    "error",
                    "run_id",
                    "step_key",
                    "persons_processed",
                    "persons_updated",
                    "persons_skipped",
                ],
            )
            writer.writeheader()
            for result in failed_team_results:
                writer.writerow(
                    {
                        "team_id": result.team_id,
                        "status": result.status,
                        "error": result.error or "",
                        "run_id": result.run_id,
                        "step_key": result.step_key,
                        "persons_processed": result.persons_processed,
                        "persons_updated": result.persons_updated,
                        "persons_skipped": result.persons_skipped,
                    }
                )
        print(f"Wrote {len(failed_team_results)} failed team records to {args.output_csv}")

    # Exit with error code if there were failures
    if deduped_failed_team_ids:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
