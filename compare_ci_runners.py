#!/usr/bin/env python3
import csv
from typing import Dict, List


def parse_job_csv_with_runners(file_path: str) -> Dict[str, Dict]:
    """Parse job CSV including runner information."""
    jobs = {}
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            job_key = next(k for k in row.keys() if 'Job' in k and 'job failures' not in k)
            failure_key = next(k for k in row.keys() if 'Failure rate' in k)
            runtime_key = next(k for k in row.keys() if 'Avg run time' in k)
            queue_key = next(k for k in row.keys() if 'queue time' in k)
            runs_key = next(k for k in row.keys() if 'Job runs' in k)
            runner_type_key = next(k for k in row.keys() if 'Runner type' in k)
            runner_labels_key = next(k for k in row.keys() if 'Runner labels' in k)

            job = row[job_key].strip('"').strip("'")

            # Skip Python 3.12 jobs
            if 'Py 3.12' in job:
                continue

            jobs[job] = {
                'failure_rate': float(row[failure_key].strip('"')),
                'avg_run_time': int(row[runtime_key].strip('"')),
                'avg_queue_time': int(row[queue_key].strip('"').replace("'", "")),
                'job_runs': int(row[runs_key].strip('"')),
                'runner_type': row[runner_type_key].strip('"').strip("'"),
                'runner_labels': row[runner_labels_key].strip('"').strip("'")
            }
    return jobs


def main():
    oct_1 = parse_job_csv_with_runners('/Users/julian/Downloads/146587bd-e068-4d9c-aaff-8168a1e476e7.csv')
    oct_9_10 = parse_job_csv_with_runners('/Users/julian/Downloads/9889ac49-05e4-4370-9639-ef510bfd63a8.csv')

    print("=" * 160)
    print("CI RUNNER TYPE ANALYSIS: OCT 1 vs OCT 9-10")
    print("=" * 160)
    print()

    # Find jobs that exist in both periods
    common_jobs = set(oct_1.keys()) & set(oct_9_10.keys())

    # Find jobs where runner changed
    runner_changes = []
    for job in common_jobs:
        old = oct_1[job]
        new = oct_9_10[job]

        old_runner = old['runner_labels']
        new_runner = new['runner_labels']

        if old_runner != new_runner:
            runtime_diff = new['avg_run_time'] - old['avg_run_time']
            runtime_pct = (runtime_diff / old['avg_run_time'] * 100) if old['avg_run_time'] > 0 else 0

            runner_changes.append({
                'job': job,
                'old_runner': old_runner,
                'new_runner': new_runner,
                'old_time': old['avg_run_time'],
                'new_time': new['avg_run_time'],
                'diff': runtime_diff,
                'pct': runtime_pct,
                'old_runs': old['job_runs'],
                'new_runs': new['job_runs']
            })

    print(f"JOBS WITH RUNNER TYPE CHANGES (n={len(runner_changes)} out of {len(common_jobs)} common jobs)")
    print("-" * 160)
    if runner_changes:
        print(f"{'Job':<60} {'Oct 1 Runner':<25} {'Oct 9-10 Runner':<25} {'Runtime Change':>20} {'Runs':>12}")
        print("-" * 160)

        runner_changes.sort(key=lambda x: abs(x['diff']), reverse=True)

        for change in runner_changes:
            job_short = change['job'][:57] + '...' if len(change['job']) > 60 else change['job']
            old_r = change['old_runner'][:22] + '...' if len(change['old_runner']) > 25 else change['old_runner']
            new_r = change['new_runner'][:22] + '...' if len(change['new_runner']) > 25 else change['new_runner']

            print(f"{job_short:<60} {old_r:<25} {new_r:<25} "
                  f"{change['diff']:+10,d}ms ({change['pct']:+5.0f}%) "
                  f"{change['old_runs']:>4}→{change['new_runs']:<4}")
    else:
        print("No runner type changes detected!")

    print()
    print("RUNNER TYPE DISTRIBUTION")
    print("-" * 160)

    # Count jobs by runner type in each period
    oct_1_runners = {}
    oct_9_10_runners = {}

    for job, data in oct_1.items():
        runner = data['runner_labels']
        if runner not in oct_1_runners:
            oct_1_runners[runner] = {'count': 0, 'total_time': 0}
        oct_1_runners[runner]['count'] += 1
        oct_1_runners[runner]['total_time'] += data['avg_run_time'] * data['job_runs']

    for job, data in oct_9_10.items():
        runner = data['runner_labels']
        if runner not in oct_9_10_runners:
            oct_9_10_runners[runner] = {'count': 0, 'total_time': 0}
        oct_9_10_runners[runner]['count'] += 1
        oct_9_10_runners[runner]['total_time'] += data['avg_run_time'] * data['job_runs']

    all_runners = sorted(set(oct_1_runners.keys()) | set(oct_9_10_runners.keys()))

    print(f"{'Runner':<40} {'Oct 1 Jobs':>12} {'Oct 9-10 Jobs':>12} {'Oct 1 Total Time':>20} {'Oct 9-10 Total Time':>20}")
    print("-" * 160)

    for runner in all_runners:
        oct_1_count = oct_1_runners.get(runner, {'count': 0, 'total_time': 0})['count']
        oct_9_10_count = oct_9_10_runners.get(runner, {'count': 0, 'total_time': 0})['count']
        oct_1_time = oct_1_runners.get(runner, {'count': 0, 'total_time': 0})['total_time']
        oct_9_10_time = oct_9_10_runners.get(runner, {'count': 0, 'total_time': 0})['total_time']

        runner_short = runner[:37] + '...' if len(runner) > 40 else runner

        print(f"{runner_short:<40} {oct_1_count:>12} {oct_9_10_count:>12} "
              f"{oct_1_time:>18,d}ms {oct_9_10_time:>18,d}ms")

    # Jobs that significantly regressed - group by runner
    print()
    print("SIGNIFICANT REGRESSIONS GROUPED BY RUNNER TYPE")
    print("-" * 160)

    # Get the statistically significant regressions
    regressions_by_runner = {}

    for job in common_jobs:
        old = oct_1[job]
        new = oct_9_10[job]

        # Only jobs with at least 50 runs in new period and >50% slowdown
        if new['job_runs'] >= 50 and new['avg_run_time'] > old['avg_run_time'] * 1.5:
            runner = new['runner_labels']
            if runner not in regressions_by_runner:
                regressions_by_runner[runner] = []

            runtime_diff = new['avg_run_time'] - old['avg_run_time']
            runtime_pct = (runtime_diff / old['avg_run_time'] * 100)

            regressions_by_runner[runner].append({
                'job': job,
                'old_time': old['avg_run_time'],
                'new_time': new['avg_run_time'],
                'diff': runtime_diff,
                'pct': runtime_pct,
                'runs': new['job_runs']
            })

    for runner in sorted(regressions_by_runner.keys()):
        jobs = regressions_by_runner[runner]
        jobs.sort(key=lambda x: x['pct'], reverse=True)

        print(f"\n{runner} ({len(jobs)} jobs with >50% regression):")
        print("-" * 160)
        for job_data in jobs[:10]:  # Top 10 per runner
            job_short = job_data['job'][:80]
            print(f"  {job_short:<80} {job_data['old_time']:>10,d}ms → {job_data['new_time']:>10,d}ms ({job_data['pct']:+.0f}%)")

    print()
    print("=" * 160)


if __name__ == '__main__':
    main()
