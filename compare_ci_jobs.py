#!/usr/bin/env python3
import csv
from typing import Dict


def parse_job_csv(file_path: str) -> Dict[str, Dict]:
    """Parse job CSV and return metrics indexed by job name."""
    jobs = {}
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            job_key = next(k for k in row.keys() if 'Job' in k and 'job failures' not in k)
            failure_key = next(k for k in row.keys() if 'Failure rate' in k)
            runtime_key = next(k for k in row.keys() if 'Avg run time' in k)
            queue_key = next(k for k in row.keys() if 'queue time' in k)
            runs_key = next(k for k in row.keys() if 'Job runs' in k)

            job = row[job_key].strip('"').strip("'")
            jobs[job] = {
                'failure_rate': float(row[failure_key].strip('"')),
                'avg_run_time': int(row[runtime_key].strip('"')),
                'avg_queue_time': int(row[queue_key].strip('"').replace("'", "")),
                'job_runs': int(row[runs_key].strip('"'))
            }
    return jobs


def main():
    oct_1 = parse_job_csv('/Users/julian/Downloads/146587bd-e068-4d9c-aaff-8168a1e476e7.csv')
    oct_9_10 = parse_job_csv('/Users/julian/Downloads/9889ac49-05e4-4370-9639-ef510bfd63a8.csv')

    print("=" * 140)
    print("CI JOB PERFORMANCE COMPARISON: OCT 1 vs OCT 9-10")
    print("=" * 140)
    print()

    # Calculate totals
    oct_1_total = sum(j['avg_run_time'] * j['job_runs'] for j in oct_1.values())
    oct_9_10_total = sum(j['avg_run_time'] * j['job_runs'] for j in oct_9_10.values())
    oct_1_runs = sum(j['job_runs'] for j in oct_1.values())
    oct_9_10_runs = sum(j['job_runs'] for j in oct_9_10.values())

    print("OVERALL SUMMARY")
    print("-" * 140)
    print(f"Oct 1:       {oct_1_runs:6,d} job runs, {oct_1_total:15,d}ms total, {oct_1_total//oct_1_runs:8,d}ms avg")
    print(f"Oct 9-10:    {oct_9_10_runs:6,d} job runs, {oct_9_10_total:15,d}ms total, {oct_9_10_total//oct_9_10_runs:8,d}ms avg")
    diff = oct_9_10_total - oct_1_total
    diff_pct = (diff / oct_1_total * 100) if oct_1_total > 0 else 0
    print(f"Change:      {oct_9_10_runs - oct_1_runs:+7,d} job runs, {diff:+16,d}ms ({diff_pct:+.1f}%)")
    print()

    # Find jobs that exist in both periods
    common_jobs = set(oct_1.keys()) & set(oct_9_10.keys())
    changes = []

    for job in common_jobs:
        old = oct_1[job]
        new = oct_9_10[job]
        runtime_diff = new['avg_run_time'] - old['avg_run_time']
        runtime_pct = (runtime_diff / old['avg_run_time'] * 100) if old['avg_run_time'] > 0 else 0

        changes.append({
            'job': job,
            'old': old,
            'new': new,
            'runtime_diff': runtime_diff,
            'runtime_pct': runtime_pct,
            'old_total': old['avg_run_time'] * old['job_runs'],
            'new_total': new['avg_run_time'] * new['job_runs']
        })

    # Sort by biggest per-run slowdowns
    changes.sort(key=lambda x: x['runtime_diff'], reverse=True)

    print("TOP 20 JOBS BY RUNTIME SLOWDOWN (per-run average)")
    print("-" * 140)
    print(f"{'Job':<70} {'Oct 1':>12} {'Oct 9-10':>12} {'Change':>20} {'Runs':>12}")
    print("-" * 140)

    for change in changes[:20]:
        job_short = change['job'][:67] + '...' if len(change['job']) > 70 else change['job']
        old_time = change['old']['avg_run_time']
        new_time = change['new']['avg_run_time']
        diff = change['runtime_diff']
        pct = change['runtime_pct']
        runs = f"{change['old']['job_runs']}→{change['new']['job_runs']}"

        print(f"{job_short:<70} {old_time:10,d}ms {new_time:10,d}ms {diff:+10,d}ms ({pct:+5.1f}%) {runs:>12}")

    print()
    print("TOP 20 JOBS BY RUNTIME IMPROVEMENT (per-run average)")
    print("-" * 140)
    print(f"{'Job':<70} {'Oct 1':>12} {'Oct 9-10':>12} {'Change':>20} {'Runs':>12}")
    print("-" * 140)

    changes.sort(key=lambda x: x['runtime_diff'])

    for change in changes[:20]:
        job_short = change['job'][:67] + '...' if len(change['job']) > 70 else change['job']
        old_time = change['old']['avg_run_time']
        new_time = change['new']['avg_run_time']
        diff = change['runtime_diff']
        pct = change['runtime_pct']
        runs = f"{change['old']['job_runs']}→{change['new']['job_runs']}"

        print(f"{job_short:<70} {old_time:10,d}ms {new_time:10,d}ms {diff:+10,d}ms ({pct:+5.1f}%) {runs:>12}")

    print()
    print("TOP 15 JOBS BY ABSOLUTE TIME IMPACT")
    print("-" * 140)
    print(f"{'Job':<70} {'Oct 1 Total':>15} {'Oct 9-10 Total':>15} {'Change':>20}")
    print("-" * 140)

    changes.sort(key=lambda x: abs((x['new_total'] - x['old_total'])), reverse=True)

    for change in changes[:15]:
        job_short = change['job'][:67] + '...' if len(change['job']) > 70 else change['job']
        old_total = change['old_total']
        new_total = change['new_total']
        diff = new_total - old_total
        pct = (diff / old_total * 100) if old_total > 0 else 0

        print(f"{job_short:<70} {old_total:13,d}ms {new_total:13,d}ms {diff:+13,d}ms ({pct:+5.1f}%)")

    # New jobs
    new_jobs = set(oct_9_10.keys()) - set(oct_1.keys())
    if new_jobs:
        print()
        print("NEW JOBS (not present on Oct 1)")
        print("-" * 140)
        for job in sorted(new_jobs):
            data = oct_9_10[job]
            total = data['avg_run_time'] * data['job_runs']
            print(f"{job[:110]:<110} {data['avg_run_time']:10,d}ms × {data['job_runs']:4d} runs = {total:15,d}ms total")

    # Removed jobs
    removed_jobs = set(oct_1.keys()) - set(oct_9_10.keys())
    if removed_jobs:
        print()
        print("REMOVED JOBS (present on Oct 1, not on Oct 9-10)")
        print("-" * 140)
        for job in sorted(removed_jobs):
            data = oct_1[job]
            total = data['avg_run_time'] * data['job_runs']
            print(f"{job[:110]:<110} {data['avg_run_time']:10,d}ms × {data['job_runs']:4d} runs = {total:15,d}ms total")

    print()
    print("=" * 140)


if __name__ == '__main__':
    main()
