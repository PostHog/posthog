import { dayjs } from 'lib/dayjs'

import type { AutoresearchPredictionCoverageApi, AutoresearchRunApi } from './generated/api.schemas'

/** Measured score coverage and score age from the newest live champion run that recorded them. */
export interface CoverageSummary {
    coverage: AutoresearchPredictionCoverageApi
    coveragePct: number
    measuredAt: string
    /** Prediction date of the measured run, as YYYY-MM-DD. The measure reads scores from before midnight UTC of this date, so it excludes the run's own scores. */
    cutoffDate: string
    /** Days between rescores of the same person, from the oldest score age. Null until everyone has a score. */
    measuredRescoreDays: number | null
    targetRescoreDays: number
    /** Scoring runs that failed after the measured run, so the numbers can be out of date. */
    failedRunsSince: number
}

/** One day's coverage, from the newest measured run of that day. Null values mark a day with no measure. */
export interface CoveragePoint {
    day: string
    coveragePct: number | null
    ageP50Days: number | null
    ageP90Days: number | null
}

type MeasuredRun = AutoresearchRunApi & { coverage: AutoresearchPredictionCoverageApi }

function measuredRuns(runs: AutoresearchRunApi[]): MeasuredRun[] {
    return runs
        .filter((run): run is MeasuredRun => run.status === 'completed' && run.coverage != null)
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
}

function cutoffDate(run: AutoresearchRunApi): string {
    const predictionDate = run.metrics?.prediction_date
    return typeof predictionDate === 'string' ? predictionDate : run.created_at.slice(0, 10)
}

/** Shadow runs and backfills of past dates do not refresh live coverage, so their failures do not age it. */
function isLiveChampionRun(run: AutoresearchRunApi): boolean {
    return run.run_type === 'inference' && !run.metrics?.shadow && cutoffDate(run) >= run.created_at.slice(0, 10)
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
        cutoffDate: cutoffDate(latest),
        measuredRescoreDays,
        targetRescoreDays,
        failedRunsSince: runs.filter(
            (run) => isLiveChampionRun(run) && run.status === 'failed' && run.created_at > latest.created_at
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
    const days = [...byDay.keys()]
    if (days.length === 0) {
        return []
    }
    // Failed live runs after the last measure extend the axis, so trailing failed days show as gaps too.
    const lastDay = runs
        .filter((run) => isLiveChampionRun(run) && run.status === 'failed')
        .map((run) => run.created_at.slice(0, 10))
        .reduce((latest, day) => (day > latest ? day : latest), days[days.length - 1])
    // A day with no measured run stays on the axis as a gap, so failed or skipped runs stay visible.
    const points: CoveragePoint[] = []
    for (let day = dayjs.utc(days[0]); !day.isAfter(dayjs.utc(lastDay)); day = day.add(1, 'day')) {
        const key = day.format('YYYY-MM-DD')
        points.push(byDay.get(key) ?? { day: key, coveragePct: null, ageP50Days: null, ageP90Days: null })
    }
    return points
}
