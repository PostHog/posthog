import { dayjs } from 'lib/dayjs'

import { AutoresearchRunApi, CalibrationBinApi, OnlinePerformanceRowApi } from './generated/api.schemas'
import { modelQuality } from './modelQuality'
import { PREDICTION_SEGMENTS, PredictionSegmentDefinition, predictionSegmentFor } from './predictionSegments'

export interface RealizedAucPoint {
    date: string
    auc: number
    low: number | null
    high: number | null
}

export interface SegmentCalibration {
    segment: PredictionSegmentDefinition
    people: number
    /** Mean predicted probability of the segment's people. */
    predicted: number
    /** Fraction of the segment's people who did the target event. */
    actual: number
}

export function percent(value: number): string {
    return `${(value * 100).toFixed(1)}%`
}

/** The champion's row for the newest validated date. Rows come newest date first. */
export function latestChampionRow(rows: OnlinePerformanceRowApi[]): OnlinePerformanceRowApi | null {
    return rows.find((row) => row.emitted_role === 'champion') ?? null
}

/** One sentence on what the model predicted for its newest matured date and what really happened. */
export function accuracyHeadline(row: OnlinePerformanceRowApi, target: string): string {
    const date = dayjs(row.prediction_date).format('MMM D')
    const outcome = `${row.n_positive.toLocaleString()} of ${row.n_scored.toLocaleString()} people scored on ${date} did ${target} (${percent(row.base_rate)})`
    return row.mean_p_y != null ? `${outcome}. The model predicted ${percent(row.mean_p_y)}.` : `${outcome}.`
}

/** How well the model ranked people on that date, in the same words as the model list. */
export function rankingSentence(row: OnlinePerformanceRowApi, target: string): string | null {
    const quality = modelQuality({
        holdoutAuc: null,
        realizedAuc: row.realized_auc,
        liftAt10: null,
        isPreliminary: false,
        target: '',
    })
    if (!quality) {
        return null
    }
    const lift =
        row.lift_at_10 != null ? ` The top 10% were ${row.lift_at_10.toFixed(1)}× more likely to do ${target}.` : ''
    return `Ranking quality is ${quality.verdict.toLowerCase()} (realized AUC ${quality.auc.toFixed(2)}).${lift}`
}

/** The champion's realized AUC per date, oldest first, for the trend chart. */
export function realizedAucSeries(rows: OnlinePerformanceRowApi[]): RealizedAucPoint[] {
    return rows
        .filter((row) => row.emitted_role === 'champion' && row.realized_auc != null)
        .map((row) => ({
            date: row.prediction_date,
            auc: row.realized_auc as number,
            low: row.realized_auc_ci_low,
            high: row.realized_auc_ci_high,
        }))
        .sort((a, b) => a.date.localeCompare(b.date))
}

/**
 * Predicted against actual rate per likelihood segment. The quantile bins do not align with the
 * segment cut points, so each bin goes to the segment of its mean predicted probability.
 */
export function calibrationBySegment(bins: CalibrationBinApi[]): SegmentCalibration[] {
    const totals = new Map<string, { people: number; predicted: number; actual: number }>()
    for (const bin of bins) {
        const key = predictionSegmentFor(bin.mean_p_y).key
        const total = totals.get(key) ?? { people: 0, predicted: 0, actual: 0 }
        total.people += bin.n
        total.predicted += bin.n * bin.mean_p_y
        total.actual += bin.n * bin.positive_rate
        totals.set(key, total)
    }
    return PREDICTION_SEGMENTS.flatMap((segment) => {
        const total = totals.get(segment.key)
        return total && total.people > 0
            ? [
                  {
                      segment,
                      people: total.people,
                      predicted: total.predicted / total.people,
                      actual: total.actual / total.people,
                  },
              ]
            : []
    })
}

/** When the first scored date matures: the earliest completed scoring run plus the horizon. */
export function firstCheckDate(
    runs: Pick<AutoresearchRunApi, 'run_type' | 'status' | 'created_at'>[],
    horizonDays: number | undefined
): dayjs.Dayjs | null {
    const firstScored = runs
        .filter((run) => run.run_type === 'inference' && run.status === 'completed')
        .map((run) => dayjs(run.created_at))
        .sort((a, b) => a.valueOf() - b.valueOf())[0]
    return firstScored ? firstScored.add(horizonDays ?? 0, 'day') : null
}
