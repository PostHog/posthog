import type { AutoresearchPredictionCoverageApi, AutoresearchRunApi } from './generated/api.schemas'

/** Measured score coverage and score age from the newest live champion run that recorded them. */
export interface CoverageSummary {
    coverage: AutoresearchPredictionCoverageApi
    coveragePct: number
    measuredAt: string
    /** Days between rescores of the same person, from the oldest score age. Null until everyone has a score. */
    measuredRescoreDays: number | null
    targetRescoreDays: number
    /** Scoring runs that failed after the measured run, so the numbers can be out of date. */
    failedRunsSince: number
}

/** One day's coverage, from the newest measured run of that day. */
export interface CoveragePoint {
    day: string
    coveragePct: number
    ageP50Days: number | null
    ageP90Days: number | null
}

type MeasuredRun = AutoresearchRunApi & { coverage: AutoresearchPredictionCoverageApi }

function measuredRuns(runs: AutoresearchRunApi[]): MeasuredRun[] {
    return runs
        .filter((run): run is MeasuredRun => run.status === 'completed' && run.coverage != null)
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
}

function coveragePct(coverage: AutoresearchPredictionCoverageApi): number {
    return coverage.population > 0 ? (100 * coverage.with_score) / coverage.population : 0
}

export function coverageSummary(runs: AutoresearchRunApi[], targetRescoreDays: number): CoverageSummary | null {
    const measured = measuredRuns(runs)
    const latest = measured[measured.length - 1]
    if (!latest) {
        return null
    }
    const { coverage } = latest
    const measuredRescoreDays =
        coverage.never_scored === 0 && coverage.age_days_max != null
            ? Math.max(1, Math.round(coverage.age_days_max))
            : null
    return {
        coverage,
        coveragePct: coveragePct(coverage),
        measuredAt: latest.created_at,
        measuredRescoreDays,
        targetRescoreDays,
        failedRunsSince: runs.filter(
            (run) => run.run_type === 'inference' && run.status === 'failed' && run.created_at > latest.created_at
        ).length,
    }
}

/** Coverage and score age per day, oldest day first. Reads the runs list, so it needs no extra query. */
export function coverageHistory(runs: AutoresearchRunApi[]): CoveragePoint[] {
    const byDay = new Map<string, CoveragePoint>()
    for (const run of measuredRuns(runs)) {
        const day = run.created_at.slice(0, 10)
        byDay.set(day, {
            day,
            coveragePct: coveragePct(run.coverage),
            ageP50Days: run.coverage.age_days_p50,
            ageP90Days: run.coverage.age_days_p90,
        })
    }
    return [...byDay.values()]
}
