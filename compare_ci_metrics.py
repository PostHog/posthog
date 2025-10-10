#!/usr/bin/env python3
import csv
from pathlib import Path
from typing import Dict, List, Tuple


def parse_csv(file_path: str) -> Dict[str, Dict]:
    """Parse CSV and return workflow metrics indexed by workflow name."""
    workflows = {}
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Handle both quoted and unquoted headers
            workflow_key = next(k for k in row.keys() if 'Workflow' in k)
            failure_key = next(k for k in row.keys() if 'job failures' in k)
            runtime_key = next(k for k in row.keys() if 'run time' in k)
            runs_key = next(k for k in row.keys() if 'Workflow runs' in k)
            jobs_key = next(k for k in row.keys() if 'Jobs' in k)

            workflow = row[workflow_key].strip('"').strip("'")
            workflows[workflow] = {
                'failure_rate': float(row[failure_key].strip('"')),
                'avg_run_time': int(row[runtime_key].strip('"')),
                'workflow_runs': int(row[runs_key].strip('"')),
                'jobs': int(row[jobs_key].strip('"'))
            }
    return workflows


def compare_metrics(last_week: Dict, this_week: Dict) -> None:
    """Compare metrics between two periods and print analysis."""

    all_workflows = set(last_week.keys()) | set(this_week.keys())

    print("=" * 120)
    print("CI WORKFLOW PERFORMANCE COMPARISON")
    print("=" * 120)
    print()

    # Calculate totals
    last_week_total_time = sum(w['avg_run_time'] * w['workflow_runs'] for w in last_week.values())
    this_week_total_time = sum(w['avg_run_time'] * w['workflow_runs'] for w in this_week.values())
    last_week_total_runs = sum(w['workflow_runs'] for w in last_week.values())
    this_week_total_runs = sum(w['workflow_runs'] for w in this_week.values())

    print("OVERALL SUMMARY")
    print("-" * 120)
    print(f"Last week (Oct 3-4):  {last_week_total_runs:5d} runs, {last_week_total_time:12,d}ms total, {last_week_total_time//last_week_total_runs:8,d}ms avg")
    print(f"This week (Oct 9-10): {this_week_total_runs:5d} runs, {this_week_total_time:12,d}ms total, {this_week_total_time//this_week_total_runs:8,d}ms avg")
    total_time_diff = this_week_total_time - last_week_total_time
    total_time_pct = (total_time_diff / last_week_total_time * 100) if last_week_total_time > 0 else 0
    print(f"Change:              {this_week_total_runs - last_week_total_runs:+6d} runs, {total_time_diff:+13,d}ms ({total_time_pct:+.1f}%)")
    print()

    # Find workflows with biggest changes
    changes: List[Tuple[str, Dict, Dict, float]] = []

    for workflow in all_workflows:
        last = last_week.get(workflow)
        this = this_week.get(workflow)

        if last and this:
            last_total = last['avg_run_time'] * last['workflow_runs']
            this_total = this['avg_run_time'] * this['workflow_runs']
            diff = this_total - last_total
            changes.append((workflow, last, this, diff))

    # Sort by absolute time impact
    changes.sort(key=lambda x: abs(x[3]), reverse=True)

    print("TOP 15 WORKFLOWS BY ABSOLUTE TIME IMPACT")
    print("-" * 120)
    print(f"{'Workflow':<50} {'Last Week':>15} {'This Week':>15} {'Change':>20}")
    print(f"{'':50} {'(runs × avg)':>15} {'(runs × avg)':>15} {'':>20}")
    print("-" * 120)

    for workflow, last, this, diff in changes[:15]:
        last_total = last['avg_run_time'] * last['workflow_runs']
        this_total = this['avg_run_time'] * this['workflow_runs']
        pct_change = (diff / last_total * 100) if last_total > 0 else 0

        workflow_short = workflow.replace('.github/workflows/', '').replace('dynamic/', '')
        if len(workflow_short) > 47:
            workflow_short = workflow_short[:44] + '...'

        last_str = f"{last['workflow_runs']:3d} × {last['avg_run_time']:7,d}ms"
        this_str = f"{this['workflow_runs']:3d} × {this['avg_run_time']:7,d}ms"
        change_str = f"{diff:+13,d}ms ({pct_change:+6.1f}%)"

        print(f"{workflow_short:<50} {last_str:>15} {this_str:>15} {change_str:>20}")

    print()
    print("TOP 10 WORKFLOWS BY RUNTIME INCREASE (per-run average)")
    print("-" * 120)
    print(f"{'Workflow':<50} {'Last Week':>12} {'This Week':>12} {'Change':>15}")
    print("-" * 120)

    runtime_changes = [(w, l, t, t['avg_run_time'] - l['avg_run_time'])
                       for w, l, t, _ in changes]
    runtime_changes.sort(key=lambda x: x[3], reverse=True)

    for workflow, last, this, diff in runtime_changes[:10]:
        workflow_short = workflow.replace('.github/workflows/', '').replace('dynamic/', '')
        if len(workflow_short) > 47:
            workflow_short = workflow_short[:44] + '...'

        pct_change = (diff / last['avg_run_time'] * 100) if last['avg_run_time'] > 0 else 0
        print(f"{workflow_short:<50} {last['avg_run_time']:10,d}ms {this['avg_run_time']:10,d}ms {diff:+10,d}ms ({pct_change:+5.1f}%)")

    print()
    print("FAILURE RATE CHANGES (workflows with >5% change)")
    print("-" * 120)
    print(f"{'Workflow':<50} {'Last Week':>12} {'This Week':>12} {'Change':>12}")
    print("-" * 120)

    failure_changes = []
    for workflow, last, this, _ in changes:
        failure_diff = this['failure_rate'] - last['failure_rate']
        if abs(failure_diff) > 5.0:
            failure_changes.append((workflow, last, this, failure_diff))

    failure_changes.sort(key=lambda x: abs(x[3]), reverse=True)

    for workflow, last, this, diff in failure_changes:
        workflow_short = workflow.replace('.github/workflows/', '').replace('dynamic/', '')
        if len(workflow_short) > 47:
            workflow_short = workflow_short[:44] + '...'

        print(f"{workflow_short:<50} {last['failure_rate']:11.2f}% {this['failure_rate']:11.2f}% {diff:+11.2f}%")

    if not failure_changes:
        print("No significant failure rate changes detected.")

    print()
    print("=" * 120)


if __name__ == '__main__':
    last_week = parse_csv('/Users/julian/Downloads/0b8a9bd0-e668-4afa-b846-c2851ddd9368.csv')
    this_week = parse_csv('/Users/julian/Downloads/d93d0862-82f9-41bd-82a3-fb4f6cfedf89.csv')
    compare_metrics(last_week, this_week)
