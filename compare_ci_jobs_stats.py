#!/usr/bin/env python3
import csv
from typing import Dict, List, Tuple
import math


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

            # Skip Python 3.12 jobs
            if 'Py 3.12' in job:
                continue

            jobs[job] = {
                'failure_rate': float(row[failure_key].strip('"')),
                'avg_run_time': int(row[runtime_key].strip('"')),
                'avg_queue_time': int(row[queue_key].strip('"').replace("'", "")),
                'job_runs': int(row[runs_key].strip('"'))
            }
    return jobs


def calculate_pooled_stderr(n1: int, n2: int, mean1: float, mean2: float) -> float:
    """
    Calculate pooled standard error for comparing two means.
    Assumes we don't have individual measurements, only means and sample sizes.
    Uses a conservative estimate assuming high variance (CV = 0.3).
    """
    # Conservative coefficient of variation estimate for CI runtimes
    cv = 0.3

    # Estimate standard deviations from means
    sd1 = mean1 * cv
    sd2 = mean2 * cv

    # Pooled standard error
    se = math.sqrt((sd1**2 / n1) + (sd2**2 / n2))
    return se


def calculate_welch_t_test(n1: int, n2: int, mean1: float, mean2: float, se: float) -> Tuple[float, float, str]:
    """
    Calculate Welch's t-test statistic and approximate p-value.
    Returns (t_statistic, degrees_of_freedom, significance_level).
    """
    if se == 0:
        return (0.0, 0, "N/A")

    t = (mean2 - mean1) / se

    # Welch-Satterthwaite degrees of freedom approximation
    cv = 0.3
    sd1 = mean1 * cv
    sd2 = mean2 * cv
    var1 = sd1**2 / n1
    var2 = sd2**2 / n2

    df = ((var1 + var2)**2) / ((var1**2 / (n1 - 1)) + (var2**2 / (n2 - 1))) if n1 > 1 and n2 > 1 else min(n1, n2) - 1

    # Rough p-value approximation using t-distribution critical values
    abs_t = abs(t)
    if df < 1:
        sig = "N/A"
    elif abs_t > 3.3:  # p < 0.001
        sig = "***"
    elif abs_t > 2.6:  # p < 0.01
        sig = "**"
    elif abs_t > 2.0:  # p < 0.05
        sig = "*"
    else:
        sig = "n.s."

    return (t, df, sig)


def effect_size_cohens_d(mean1: float, mean2: float) -> float:
    """Calculate Cohen's d effect size."""
    cv = 0.3
    pooled_sd = math.sqrt((mean1 * cv)**2 + (mean2 * cv)**2) / math.sqrt(2)
    if pooled_sd == 0:
        return 0.0
    return (mean2 - mean1) / pooled_sd


def main():
    oct_1 = parse_job_csv('/Users/julian/Downloads/146587bd-e068-4d9c-aaff-8168a1e476e7.csv')
    oct_9_10 = parse_job_csv('/Users/julian/Downloads/9889ac49-05e4-4370-9639-ef510bfd63a8.csv')

    print("=" * 160)
    print("CI JOB PERFORMANCE STATISTICAL ANALYSIS: OCT 1 vs OCT 9-10")
    print("=" * 160)
    print()
    print("Statistical Methods:")
    print("- Welch's t-test for comparing means (accounts for unequal sample sizes)")
    print("- Conservative variance estimate (CV=0.3) based on typical CI runtime variability")
    print("- Significance: *** p<0.001, ** p<0.01, * p<0.05, n.s. = not significant")
    print("- Cohen's d effect size: |d|<0.2 small, 0.2-0.5 medium, 0.5-0.8 large, >0.8 very large")
    print()

    # Find jobs that exist in both periods
    common_jobs = set(oct_1.keys()) & set(oct_9_10.keys())

    stats = []
    for job in common_jobs:
        old = oct_1[job]
        new = oct_9_10[job]

        n1 = old['job_runs']
        n2 = new['job_runs']
        mean1 = old['avg_run_time']
        mean2 = new['avg_run_time']

        # Skip if either has very few runs
        if n1 < 3 or n2 < 3:
            continue

        diff = mean2 - mean1
        pct_change = (diff / mean1 * 100) if mean1 > 0 else 0

        se = calculate_pooled_stderr(n1, n2, mean1, mean2)
        t_stat, df, sig = calculate_welch_t_test(n1, n2, mean1, mean2, se)
        cohens_d = effect_size_cohens_d(mean1, mean2)

        # 95% confidence interval for the difference
        ci_margin = 1.96 * se
        ci_lower = diff - ci_margin
        ci_upper = diff + ci_margin

        stats.append({
            'job': job,
            'mean1': mean1,
            'mean2': mean2,
            'n1': n1,
            'n2': n2,
            'diff': diff,
            'pct_change': pct_change,
            't_stat': t_stat,
            'df': df,
            'sig': sig,
            'cohens_d': cohens_d,
            'ci_lower': ci_lower,
            'ci_upper': ci_upper,
            'se': se
        })

    # Filter for statistically significant changes only
    significant_stats = [s for s in stats if s['sig'] in ['*', '**', '***']]

    print(f"STATISTICALLY SIGNIFICANT REGRESSIONS (slower on Oct 9-10, n={len(common_jobs)} jobs compared)")
    print("-" * 160)
    print(f"{'Job':<75} {'Oct 1':>11} {'Oct 9-10':>11} {'Change':>15} {'t-stat':>8} {'p-val':>6} {'Effect':>7} {'Runs':>12}")
    print("-" * 160)

    regressions = [s for s in significant_stats if s['diff'] > 0]
    regressions.sort(key=lambda x: abs(x['t_stat']), reverse=True)

    for s in regressions[:30]:
        job_short = s['job'][:72] + '...' if len(s['job']) > 75 else s['job']
        print(f"{job_short:<75} {s['mean1']:9,.0f}ms {s['mean2']:9,.0f}ms "
              f"{s['diff']:+8,.0f}ms ({s['pct_change']:+4.0f}%) "
              f"{s['t_stat']:7.2f} {s['sig']:>6} "
              f"{s['cohens_d']:6.2f} "
              f"{s['n1']:>4}→{s['n2']:<4}")

    print()
    print(f"STATISTICALLY SIGNIFICANT IMPROVEMENTS (faster on Oct 9-10)")
    print("-" * 160)
    print(f"{'Job':<75} {'Oct 1':>11} {'Oct 9-10':>11} {'Change':>15} {'t-stat':>8} {'p-val':>6} {'Effect':>7} {'Runs':>12}")
    print("-" * 160)

    improvements = [s for s in significant_stats if s['diff'] < 0]
    improvements.sort(key=lambda x: abs(x['t_stat']), reverse=True)

    for s in improvements[:30]:
        job_short = s['job'][:72] + '...' if len(s['job']) > 75 else s['job']
        print(f"{job_short:<75} {s['mean1']:9,.0f}ms {s['mean2']:9,.0f}ms "
              f"{s['diff']:+8,.0f}ms ({s['pct_change']:+4.0f}%) "
              f"{s['t_stat']:7.2f} {s['sig']:>6} "
              f"{s['cohens_d']:6.2f} "
              f"{s['n1']:>4}→{s['n2']:<4}")

    print()
    print("NOT STATISTICALLY SIGNIFICANT CHANGES (may be noise)")
    print("-" * 160)
    non_sig = [s for s in stats if s['sig'] == 'n.s.' and abs(s['pct_change']) > 10]
    non_sig.sort(key=lambda x: abs(x['diff']), reverse=True)

    print(f"{'Job':<75} {'Oct 1':>11} {'Oct 9-10':>11} {'Change':>15} {'t-stat':>8} {'Runs':>12}")
    print("-" * 160)

    for s in non_sig[:20]:
        job_short = s['job'][:72] + '...' if len(s['job']) > 75 else s['job']
        print(f"{job_short:<75} {s['mean1']:9,.0f}ms {s['mean2']:9,.0f}ms "
              f"{s['diff']:+8,.0f}ms ({s['pct_change']:+4.0f}%) "
              f"{s['t_stat']:7.2f} "
              f"{s['n1']:>4}→{s['n2']:<4}")

    # Overall summary statistics
    print()
    print("SUMMARY STATISTICS")
    print("-" * 160)

    sig_regressions = [s for s in significant_stats if s['diff'] > 0]
    sig_improvements = [s for s in significant_stats if s['diff'] < 0]

    print(f"Jobs with statistically significant regressions: {len(sig_regressions)}")
    print(f"Jobs with statistically significant improvements: {len(sig_improvements)}")
    print(f"Jobs with no significant change: {len(stats) - len(significant_stats)}")

    if sig_regressions:
        avg_regression = sum(s['pct_change'] for s in sig_regressions) / len(sig_regressions)
        median_regression = sorted([s['pct_change'] for s in sig_regressions])[len(sig_regressions)//2]
        print(f"Average regression magnitude: {avg_regression:+.1f}%")
        print(f"Median regression magnitude: {median_regression:+.1f}%")

    if sig_improvements:
        avg_improvement = sum(s['pct_change'] for s in sig_improvements) / len(sig_improvements)
        median_improvement = sorted([s['pct_change'] for s in sig_improvements])[len(sig_improvements)//2]
        print(f"Average improvement magnitude: {avg_improvement:+.1f}%")
        print(f"Median improvement magnitude: {median_improvement:+.1f}%")

    # Largest effect sizes
    print()
    print("LARGEST EFFECT SIZES (Cohen's d)")
    print("-" * 160)
    stats.sort(key=lambda x: abs(x['cohens_d']), reverse=True)

    for s in stats[:15]:
        job_short = s['job'][:72] + '...' if len(s['job']) > 75 else s['job']
        direction = "slower" if s['diff'] > 0 else "faster"
        print(f"{job_short:<75} d={s['cohens_d']:+.3f} ({direction}, {s['sig']})")

    print()
    print("=" * 160)


if __name__ == '__main__':
    main()
