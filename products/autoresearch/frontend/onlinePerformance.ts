import { dayjs } from 'lib/dayjs'

import {
    AutoresearchRunApi,
    CalibrationBinApi,
    ConfusionByCutoffApi,
    OnlinePerformanceRowApi,
} from './generated/api.schemas'
import { modelQuality } from './modelQuality'
import { eventName } from './pipelineQuestion'
import {
    PredictionSegmentDefinition,
    PredictionSegmentThresholds,
    predictionSegmentFor,
    predictionSegmentDefinitions,
} from './predictionSegments'

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

export type AccuracyCutoff = keyof ConfusionByCutoffApi

export const ACCURACY_CUTOFFS: { key: AccuracyCutoff; label: string }[] = [
    { key: 'top_10', label: 'Top 10%' },
    { key: 'top_20', label: 'Top 20%' },
    { key: 'likely', label: 'Likely' },
]

/** Confusion counts of one cutoff, summed over the champion's checked dates that have them. */
export interface PooledConfusion {
    tp: number
    fp: number
    fn: number
    tn: number
    flagged: number
    precision: number | null
    recall: number | null
    firstDate: string
    lastDate: string
    /** Champion dates shown on the tab that were checked before confusion counts existed. */
    datesWithoutCounts: number
}

export function percent(value: number): string {
    return `${(value * 100).toFixed(1)}%`
}

/** The champion's row for the newest validated date. Rows come newest date first. */
export function latestChampionRow(rows: OnlinePerformanceRowApi[]): OnlinePerformanceRowApi | null {
    return rows.find((row) => row.emitted_role === 'champion') ?? null
}

export interface AccuracyStat {
    key: 'ranking' | 'lift' | 'rate' | 'people'
    label: string
    value: string
    /** The supporting number and the date the stat covers. */
    detail: string
    tooltip: string
}

/** The four headline stats for the champion's newest checked date. Each stat names that date. */
export function accuracyStats(row: OnlinePerformanceRowApi, target: string): AccuracyStat[] {
    const date = `scored on ${dayjs(row.prediction_date).format('MMM D')}`
    // Lift has no meaning when no one did the target, and the backend reports 0 then.
    const lift = row.n_positive > 0 ? row.lift_at_10 : null
    const quality = modelQuality({
        holdoutAuc: null,
        realizedAuc: row.realized_auc,
        liftAt10: null,
        isPreliminary: false,
        target: '',
    })
    return [
        {
            key: 'ranking',
            label: 'Ranking',
            value: quality?.verdict ?? '—',
            detail: quality ? `AUC ${quality.auc.toFixed(2)}, ${date}` : `No AUC, ${date}`,
            tooltip: `How well the model ranked people who did ${eventName(target)} above people who did not. Realized AUC 0.5 is a coin flip and 1 is a perfect ranking.`,
        },
        {
            key: 'lift',
            label: 'Top 10% lift',
            value: lift != null ? `${lift.toFixed(1)}×` : '—',
            detail:
                row.n_positive === 0
                    ? `No one did it, ${date}`
                    : lift != null
                      ? `Against everyone, ${date}`
                      : `Not measured, ${date}`,
            tooltip: `How many times more likely the top 10% were to do ${eventName(target)} than everyone the model scored.`,
        },
        {
            key: 'rate',
            label: 'Actual rate',
            value: percent(row.base_rate),
            detail: row.mean_p_y != null ? `Predicted ${percent(row.mean_p_y)}, ${date}` : date,
            tooltip: `The share of scored people who did ${eventName(target)}, against the average score the model gave them.`,
        },
        {
            key: 'people',
            label: 'People checked',
            value: row.n_scored.toLocaleString(),
            detail: `${row.n_positive.toLocaleString()} did it, ${date}`,
            tooltip: `The people the model scored on that date, and how many of them did ${eventName(target)} in the horizon.`,
        },
    ]
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
export function calibrationBySegment(
    bins: CalibrationBinApi[],
    thresholds: PredictionSegmentThresholds
): SegmentCalibration[] {
    const totals = new Map<string, { people: number; predicted: number; actual: number }>()
    for (const bin of bins) {
        const key = predictionSegmentFor(bin.mean_p_y, thresholds).key
        const total = totals.get(key) ?? { people: 0, predicted: 0, actual: 0 }
        total.people += bin.n
        total.predicted += bin.n * bin.mean_p_y
        total.actual += bin.n * bin.positive_rate
        totals.set(key, total)
    }
    return predictionSegmentDefinitions(thresholds).flatMap((segment) => {
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

/**
 * Sum one cutoff's confusion counts over the matured dates of the current champion. Rows checked
 * before confusion counts existed have none, so they are counted apart instead of read as zeros.
 */
export function pooledConfusion(rows: OnlinePerformanceRowApi[], cutoff: AccuracyCutoff): PooledConfusion | null {
    const latest = latestChampionRow(rows)
    if (!latest) {
        return null
    }
    const championRows = rows.filter((row) => row.model_id === latest.model_id && row.emitted_role === 'champion')
    const withCounts = championRows.filter((row) => row.confusion != null)
    if (withCounts.length === 0) {
        return null
    }
    const total = { tp: 0, fp: 0, fn: 0, tn: 0 }
    for (const row of withCounts) {
        const counts = (row.confusion as ConfusionByCutoffApi)[cutoff]
        total.tp += counts.tp
        total.fp += counts.fp
        total.fn += counts.fn
        total.tn += counts.tn
    }
    const flagged = total.tp + total.fp
    const positives = total.tp + total.fn
    const dates = withCounts.map((row) => row.prediction_date).sort()
    return {
        ...total,
        flagged,
        precision: flagged > 0 ? total.tp / flagged : null,
        recall: positives > 0 ? total.tp / positives : null,
        firstDate: dates[0],
        lastDate: dates[dates.length - 1],
        datesWithoutCounts: championRows.length - withCounts.length,
    }
}

/** The dates the pooled counts cover, as "Feb 10 to Feb 14, 2026" or one date. */
export function confusionDateRange({ firstDate, lastDate }: Pick<PooledConfusion, 'firstDate' | 'lastDate'>): string {
    const last = dayjs(lastDate).format('MMM D, YYYY')
    return firstDate === lastDate ? last : `${dayjs(firstDate).format('MMM D')} to ${last}`
}

/** The group of people a cutoff flags, in words that fit "{share} of {group} did X". */
function cutoffGroup(cutoff: AccuracyCutoff): string {
    switch (cutoff) {
        case 'top_10':
            return 'the top 10% the model flagged'
        case 'top_20':
            return 'the top 20% the model flagged'
        case 'likely':
            return 'the people the model scored as likely'
    }
}

/** Hit rate against the overall rate, then coverage, over the pooled dates. Null when the cutoff flagged nobody. */
export function accuracySummary(confusion: PooledConfusion, cutoff: AccuracyCutoff, target: string): string | null {
    if (confusion.precision == null) {
        return null
    }
    const { firstDate, lastDate } = confusion
    const period =
        firstDate === lastDate
            ? `For people scored on ${dayjs(lastDate).format('MMM D')}`
            : `For people scored from ${dayjs(firstDate).format('MMM D')} to ${dayjs(lastDate).format('MMM D')}`
    if (confusion.recall == null) {
        return `${period}, no one did ${eventName(target)}.`
    }
    const everyone = confusion.tp + confusion.fp + confusion.fn + confusion.tn
    const overall = (confusion.tp + confusion.fn) / everyone
    return `${period}, ${percent(confusion.precision)} of ${cutoffGroup(cutoff)} did ${eventName(target)}, against ${percent(overall)} of everyone. They include ${percent(confusion.recall)} of everyone who did it.`
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

/**
 * Prediction dates that a completed validation run checked. Reads the full run history, because the
 * online_performance endpoint returns only the newest dates.
 */
export function validatedPredictionDates(
    runs: Pick<AutoresearchRunApi, 'run_type' | 'status' | 'metrics'>[]
): string[] {
    return runs.flatMap((run) => {
        const metrics = run.metrics as { prediction_date?: string; per_model?: Record<string, unknown> } | null
        return run.run_type === 'validation' &&
            run.status === 'completed' &&
            metrics?.prediction_date &&
            Object.keys(metrics.per_model ?? {}).length > 0
            ? [metrics.prediction_date]
            : []
    })
}
