import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { AutoresearchRunApi, ConfusionByCutoffApi, OnlinePerformanceRowApi } from './generated/api.schemas'
import { formatAuc, isLiftAtCeiling, liftCeilingNote, modelQuality } from './modelQuality'
import { eventName } from './pipelineQuestion'
import { PredictionSegmentThresholds, predictionSegmentFor } from './predictionSegments'

/** One group of score-ranked calibration bins, such as the top 10%. */
export interface RankCalibration {
    label: string
    /** The color of the likelihood segment the group's mean score falls in. */
    colorClassName: string
    /** Predictions in the group: people on one date, or people once per date over several dates. */
    count: number
    /** Mean predicted probability of the group. */
    predicted: number
    /** Fraction of the group who did the target event. */
    actual: number
}

/** Which checked dates the Accuracy tab summarizes: every date of the live model, or only its newest. */
export type AccuracyFrame = 'all' | 'latest'

export type AccuracyCutoff = keyof ConfusionByCutoffApi

export const ACCURACY_CUTOFFS: { key: AccuracyCutoff; label: string }[] = [
    { key: 'top_10', label: 'Top 10%' },
    { key: 'top_20', label: 'Top 20%' },
    { key: 'likely', label: 'Likely' },
]

/** Confusion counts of one cutoff, summed over the checked dates that have them. */
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
    /** Dates in the frame that were checked before confusion counts existed. */
    datesWithoutCounts: number
}

export function percent(value: number): string {
    return `${(value * 100).toFixed(1)}%`
}

/** The champion's row for the newest validated date. Rows come newest date first. */
export function latestChampionRow(rows: OnlinePerformanceRowApi[]): OnlinePerformanceRowApi | null {
    return rows.find((row) => row.emitted_role === 'champion') ?? null
}

/**
 * The dates the live model was checked as champion, newest first. The live model is the current
 * champion, or the newest champion in the rows when the models have not loaded.
 */
export function liveModelRows(
    rows: OnlinePerformanceRowApi[],
    championId: string | null | undefined
): OnlinePerformanceRowApi[] {
    const modelId = championId ?? latestChampionRow(rows)?.model_id
    return rows.filter((row) => row.model_id === modelId && row.emitted_role === 'champion')
}

/** The live model's rows that a frame covers. */
export function accuracyFrameRows(
    liveRows: OnlinePerformanceRowApi[],
    frame: AccuracyFrame
): OnlinePerformanceRowApi[] {
    return frame === 'latest' ? liveRows.slice(0, 1) : liveRows
}

export interface AccuracyStat {
    key: 'ranking' | 'lift' | 'rate' | 'people'
    label: string
    value: string
    /** The supporting number and the date the stat covers. */
    detail: string
    tooltip: string
}

function liftDetail(row: OnlinePerformanceRowApi, lift: number | null, atCeiling: boolean): string {
    if (row.n_positive === 0) {
        return 'No one did it'
    }
    if (lift == null) {
        return 'Not measured'
    }
    return atCeiling ? 'Near the maximum' : 'Against everyone'
}

/** The four headline stats for one checked date. Each stat names that date. */
function singleDateStats(row: OnlinePerformanceRowApi, target: string): AccuracyStat[] {
    const date = `scored on ${dayjs(row.prediction_date).format('MMM D')}`
    // Lift has no meaning when no one did the target, and the backend reports 0 then.
    const lift = row.n_positive > 0 ? row.lift_at_10 : null
    const liftAtCeiling = lift != null && isLiftAtCeiling(lift, 0.1, row.base_rate)
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
            detail: quality ? `AUC ${formatAuc(quality.auc)}, ${date}` : `No AUC, ${date}`,
            tooltip: `How well the model ranked people who did ${eventName(target)} above people who did not. Realized AUC 0.5 is a coin flip and 1 is a perfect ranking.`,
        },
        {
            key: 'lift',
            label: 'Top 10% lift',
            value: lift != null ? `${lift.toFixed(1)}×` : '—',
            detail: `${liftDetail(row, lift, liftAtCeiling)}, ${date}`,
            tooltip: `How many times more likely the top 10% were to do ${eventName(target)} than everyone the model scored.${liftAtCeiling ? ` ${liftCeilingNote(0.1, row.base_rate)}` : ''}`,
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

/**
 * The four headline stats over several checked dates. Each date scores everyone again, so the
 * counts are predictions: one person counts once a date.
 */
function multiDateStats(rows: OnlinePerformanceRowApi[], target: string): AccuracyStat[] {
    const scored = rows.reduce((total, row) => total + row.n_scored, 0)
    const positive = rows.reduce((total, row) => total + row.n_positive, 0)
    const baseRate = scored > 0 ? positive / scored : 0
    const aucs = rows.flatMap((row) => row.realized_auc ?? [])
    const quality = aucs.length
        ? modelQuality({
              holdoutAuc: null,
              realizedAuc: median(aucs),
              liftAt10: null,
              isPreliminary: false,
              target: '',
          })
        : null
    // A date's top 10% did the target at lift × its base rate, so lift × positives sums their hits.
    // A date where no one did it adds people and no hits. A date with positives but no lift is left out.
    const liftRows = rows.filter((row) => row.n_positive === 0 || row.lift_at_10 != null)
    const liftHits = liftRows.reduce(
        (total, row) => total + (row.n_positive > 0 ? (row.lift_at_10 ?? 0) : 0) * row.n_positive,
        0
    )
    const liftScored = liftRows.reduce((total, row) => total + row.n_scored, 0)
    const liftPositive = liftRows.reduce((total, row) => total + row.n_positive, 0)
    const lift = liftPositive > 0 ? liftHits / liftPositive : null
    return [
        {
            key: 'ranking',
            label: 'Ranking',
            value: quality?.verdict ?? '—',
            detail: !aucs.length
                ? 'No AUC'
                : aucs.length === 1
                  ? `AUC ${formatAuc(aucs[0])}`
                  : `AUC ${formatAuc(Math.min(...aucs))} to ${formatAuc(Math.max(...aucs))} by date`,
            tooltip: `How well the model ranked people who did ${eventName(target)} above people who did not, on each date. Realized AUC 0.5 is a coin flip and 1 is a perfect ranking. The label uses the median date.`,
        },
        {
            key: 'lift',
            label: 'Top 10% lift',
            value: lift != null ? `${lift.toFixed(1)}×` : '—',
            detail:
                positive === 0
                    ? 'No one did it'
                    : lift != null
                      ? `${percent(liftHits / liftScored)} against ${percent(liftPositive / liftScored)}`
                      : 'Not measured',
            tooltip: `How many times more often the top 10% of each date did ${eventName(target)} than everyone the model scored.`,
        },
        {
            key: 'rate',
            label: 'Actual rate',
            value: percent(baseRate),
            detail: `${positive.toLocaleString()} of ${scored.toLocaleString()} predictions`,
            tooltip: `The share of predictions where the person did ${eventName(target)} in the horizon.`,
        },
        {
            key: 'people',
            label: 'Predictions checked',
            value: scored.toLocaleString(),
            detail: `${pluralize(rows.length, 'date')}, each person once a date`,
            tooltip: 'The model scores everyone again on each date, so one person counts once for each checked date.',
        },
    ]
}

/** The four headline stats for the checked dates in a frame. Empty with no dates. */
export function accuracyStats(rows: OnlinePerformanceRowApi[], target: string): AccuracyStat[] {
    if (rows.length === 0) {
        return []
    }
    return rows.length === 1 ? singleDateStats(rows[0], target) : multiDateStats(rows, target)
}

export type AccuracyTrendMetric = 'ranking' | 'hit_rate' | 'coverage' | 'lift' | 'calibration'

export const ACCURACY_TREND_METRICS: { key: AccuracyTrendMetric; label: string }[] = [
    { key: 'ranking', label: 'Ranking (AUC)' },
    { key: 'hit_rate', label: 'Hit rate' },
    { key: 'coverage', label: 'Coverage' },
    { key: 'lift', label: 'Lift' },
    { key: 'calibration', label: 'Predicted and actual' },
]

export function trendMetricUsesCutoff(metric: AccuracyTrendMetric): boolean {
    return metric === 'hit_rate' || metric === 'coverage' || metric === 'lift'
}

export interface AccuracyTrendPoint {
    date: string
    value: number
    /** The 95% AUC interval. Null for every metric except ranking. */
    low: number | null
    high: number | null
}

export interface AccuracyTrendSeries {
    key: string
    label: string
    /** `actual` is the share of people who did the target, drawn next to the average score. */
    role: 'champion' | 'challenger' | 'actual'
    /** Oldest date first. A date the model has no value for is missing, not zero. */
    points: AccuracyTrendPoint[]
}

export interface AccuracyTrend {
    /** Every date any series has a value for, oldest first. */
    dates: string[]
    /** The champion series comes first. */
    series: AccuracyTrendSeries[]
    /** The champion's people scored and people who did the target, per date. */
    people: Record<string, { scored: number; positive: number }>
}

function liftAt(row: OnlinePerformanceRowApi, cutoff: AccuracyCutoff): number | null {
    // Lift has no meaning when no one did the target, and the backend reports 0 then.
    if (row.n_positive === 0) {
        return null
    }
    switch (cutoff) {
        case 'top_10':
            return row.lift_at_10
        case 'top_20':
            return row.lift_at_20
        case 'likely': {
            const precision = row.confusion?.likely.precision
            return precision != null && row.base_rate > 0 ? precision / row.base_rate : null
        }
    }
}

function trendPoint(
    row: OnlinePerformanceRowApi,
    metric: AccuracyTrendMetric,
    cutoff: AccuracyCutoff
): AccuracyTrendPoint | null {
    const point = (
        value: number | null | undefined,
        low: number | null = null,
        high: number | null = null
    ): AccuracyTrendPoint | null => (value != null ? { date: row.prediction_date, value, low, high } : null)
    switch (metric) {
        case 'ranking':
            return point(row.realized_auc, row.realized_auc_ci_low, row.realized_auc_ci_high)
        case 'hit_rate':
            return point(row.confusion?.[cutoff].precision)
        case 'coverage':
            return point(row.confusion?.[cutoff].recall)
        case 'lift':
            return point(liftAt(row, cutoff))
        case 'calibration':
            return point(row.mean_p_y)
    }
}

/**
 * One metric per prediction date, for the champion and, when asked, each model that emitted
 * predictions in another role. A row keeps the role its model held on that date, so a promoted
 * challenger's older dates stay on its challenger line.
 */
export function accuracyTrend(
    rows: OnlinePerformanceRowApi[],
    metric: AccuracyTrendMetric,
    cutoff: AccuracyCutoff,
    withChallengers: boolean
): AccuracyTrend {
    const oldestFirst = [...rows].sort((a, b) => a.prediction_date.localeCompare(b.prediction_date))
    const championRows = oldestFirst.filter((row) => row.emitted_role === 'champion')
    const pointsOf = (modelRows: OnlinePerformanceRowApi[]): AccuracyTrendPoint[] =>
        modelRows.flatMap((row) => trendPoint(row, metric, cutoff) ?? [])

    const series: AccuracyTrendSeries[] = [
        {
            key: 'champion',
            label: metric === 'calibration' ? 'Champion score' : 'Champion',
            role: 'champion',
            points: pointsOf(championRows),
        },
    ]
    if (withChallengers) {
        const challengerRows = oldestFirst.filter((row) => row.emitted_role !== 'champion')
        const challengers = [...new Set(challengerRows.map((row) => row.model_id))]
            .map((modelId) => pointsOf(challengerRows.filter((row) => row.model_id === modelId)))
            .filter((points) => points.length > 0)
        challengers.forEach((points, index) =>
            series.push({
                key: `challenger-${index}`,
                label: challengers.length > 1 ? `Challenger ${index + 1}` : 'Challenger',
                role: 'challenger',
                points,
            })
        )
    }
    if (metric === 'calibration') {
        series.push({
            key: 'actual',
            label: 'Actual rate',
            role: 'actual',
            points: championRows.map((row) => ({
                date: row.prediction_date,
                value: row.base_rate,
                low: null,
                high: null,
            })),
        })
    }

    return {
        dates: [...new Set(series.flatMap((s) => s.points.map((point) => point.date)))].sort(),
        series,
        people: Object.fromEntries(
            championRows.map((row) => [row.prediction_date, { scored: row.n_scored, positive: row.n_positive }])
        ),
    }
}

/** A metric value in its own unit. `precise` adds a decimal place to AUC for the per-date details. */
export function formatTrendValue(metric: AccuracyTrendMetric, value: number, precise = false): string {
    switch (metric) {
        case 'ranking':
            return precise ? value.toFixed(3) : formatAuc(value)
        case 'lift':
            return `${value.toFixed(1)}×`
        default:
            return percent(value)
    }
}

/** The gap between the average score and the actual rate, in percentage points with a sign. */
export function percentagePoints(gap: number): string {
    const points = (gap * 100).toFixed(1)
    return `${gap > 0 ? '+' : ''}${points} pts`
}

/** A group of score ranks in tenths from the top, from `start` up to `end`, as "Top 10%" or "Next 20%". */
function rankLabel(start: number, end: number): string {
    if (start === 0) {
        return end === 10 ? 'Everyone' : `Top ${end * 10}%`
    }
    return end === 10 ? `Bottom ${(10 - start) * 10}%` : `Next ${(end - start) * 10}%`
}

/**
 * Predicted against actual rate by score rank, pooled over the given dates. A date's bins are cut at
 * score tenths, lowest scores first, and tied scores share a bin, so a bin's tenth comes from the
 * people below it. Neighboring tenths whose mean score falls in the same likelihood segment form one
 * group, labelled by its ranks and never by the segment's cut point.
 */
export function calibrationByRank(
    rows: OnlinePerformanceRowApi[],
    thresholds: PredictionSegmentThresholds
): RankCalibration[] {
    const tenths = new Map<number, { n: number; predicted: number; actual: number }>()
    for (const row of rows) {
        const bins = row.calibration_bins ?? []
        const total = bins.reduce((sum, bin) => sum + bin.n, 0)
        let below = 0
        for (const bin of bins) {
            const tenth = Math.floor((below * 10) / total)
            below += bin.n
            const pooled = tenths.get(tenth) ?? { n: 0, predicted: 0, actual: 0 }
            pooled.n += bin.n
            pooled.predicted += bin.n * bin.mean_p_y
            pooled.actual += bin.n * bin.positive_rate
            tenths.set(tenth, pooled)
        }
    }
    const lowestFirst = [...tenths.keys()].sort((a, b) => a - b)
    const groups: (RankCalibration & { segmentKey: string; start: number; end: number })[] = []
    for (let index = lowestFirst.length - 1; index >= 0; index--) {
        const tenth = lowestFirst[index]
        const pooled = tenths.get(tenth)!
        if (pooled.n === 0) {
            continue
        }
        // A bin reaches up to the next bin, so a tied bin can cover several tenths.
        const start = 10 - (lowestFirst[index + 1] ?? 10)
        const end = 10 - tenth
        const segment = predictionSegmentFor(pooled.predicted / pooled.n, thresholds)
        const last = groups[groups.length - 1]
        if (last && last.segmentKey === segment.key) {
            last.end = end
            last.count += pooled.n
            last.predicted += pooled.predicted
            last.actual += pooled.actual
        } else {
            groups.push({
                label: '',
                colorClassName: segment.colorClassName,
                segmentKey: segment.key,
                start,
                end,
                count: pooled.n,
                predicted: pooled.predicted,
                actual: pooled.actual,
            })
        }
    }
    return groups.map(({ start, end, count, predicted, actual, colorClassName }) => ({
        label: rankLabel(start, end),
        colorClassName,
        count,
        predicted: predicted / count,
        actual: actual / count,
    }))
}

/**
 * Sum one cutoff's confusion counts over the given checked dates. Rows checked before confusion
 * counts existed have none, so they are counted apart instead of read as zeros.
 */
export function pooledConfusion(rows: OnlinePerformanceRowApi[], cutoff: AccuracyCutoff): PooledConfusion | null {
    const withCounts = rows.filter((row) => row.confusion != null)
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
        datesWithoutCounts: rows.length - withCounts.length,
    }
}

/** The dates the rows cover, as "Feb 10 to Feb 14, 2026" or one date. */
export function checkedDateRange(rows: OnlinePerformanceRowApi[]): string {
    const dates = rows.map((row) => row.prediction_date).sort()
    const last = dayjs(dates[dates.length - 1]).format('MMM D, YYYY')
    return dates[0] === dates[dates.length - 1] ? last : `${dayjs(dates[0]).format('MMM D')} to ${last}`
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

function median(values: number[]): number {
    const sorted = [...values].sort((a, b) => a - b)
    const middle = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

/** How far below the holdout AUC a date's realized AUC can be and still count as in line with training. */
const HOLDOUT_TOLERANCE = 0.02

/** Realized AUC on the given dates against the holdout AUC from training. Null when no date has an AUC. */
export function holdoutSentence(rows: OnlinePerformanceRowApi[], holdoutAuc: number | null): string | null {
    const scored = rows.filter((row) => row.realized_auc != null)
    if (scored.length === 0) {
        return null
    }
    const values = scored.map((row) => row.realized_auc as number)
    const outcome =
        values.length === 1
            ? `On real outcomes the model scored ${values[0].toFixed(3)} on ${dayjs(scored[0].prediction_date).format('MMM D')}`
            : `On real outcomes the model scored ${Math.min(...values).toFixed(3)} to ${Math.max(...values).toFixed(3)} across ${values.length} dates`
    if (holdoutAuc == null) {
        return `${outcome}.`
    }
    // Compare at the 3 decimals the sentence shows, so a gap that reads as 0.020 counts as in line.
    const inLine = values.every((value) => Number((holdoutAuc - value).toFixed(3)) <= HOLDOUT_TOLERANCE)
    return `${inLine ? 'In line with training' : 'Below training'}. ${outcome}, against ${holdoutAuc.toFixed(3)} when it was trained.`
}

/** One sentence on how the live model did on the picked metric over its checked dates. Null with no values. */
export function accuracyTrendSummary(
    rows: OnlinePerformanceRowApi[],
    metric: AccuracyTrendMetric,
    cutoff: AccuracyCutoff,
    target: string
): string | null {
    const checked = rows
        .filter((row) => row.emitted_role === 'champion')
        .flatMap((row) => {
            const point = trendPoint(row, metric, cutoff)
            return point ? [{ row, value: point.value }] : []
        })
    if (checked.length === 0) {
        return null
    }
    const values = checked.map(({ value }) => value)
    const typical = median(values)
    const single = checked.length === 1
    const lead = single ? `On ${dayjs(checked[0].row.prediction_date).format('MMM D')}` : 'On a typical date'
    const event = eventName(target)

    switch (metric) {
        case 'ranking':
            // The holdout sentence under the stat tiles covers ranking, for the dates the frame picks.
            return null
        case 'hit_rate': {
            const everyone = median(checked.map(({ row }) => row.base_rate))
            return `${lead}, ${percent(typical)} of ${cutoffGroup(cutoff)} did ${event}, against ${percent(everyone)} of everyone.`
        }
        case 'coverage':
            return `${lead}, ${cutoffGroup(cutoff)} included ${percent(typical)} of everyone who did ${event}.`
        case 'lift':
            return `${lead}, ${cutoffGroup(cutoff)} did ${event} at ${typical.toFixed(1)}× the rate of everyone.`
        case 'calibration': {
            const gaps = checked.map(({ row, value }) => value - row.base_rate)
            if (single) {
                return `${lead}, the champion's average score was ${(Math.abs(gaps[0]) * 100).toFixed(1)} points ${gaps[0] >= 0 ? 'above' : 'below'} the actual rate.`
            }
            const widest = Math.max(...gaps.map(Math.abs))
            return `Over ${checked.length} checked dates, the champion's average score stayed within ${(widest * 100).toFixed(1)} points of the actual rate.`
        }
    }
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
 * online_performance endpoint returns only the newest dates. With a champion, only the dates that
 * model was checked on as champion count, the same dates the Accuracy tab shows for the live model.
 */
export function validatedPredictionDates(
    runs: Pick<AutoresearchRunApi, 'run_type' | 'status' | 'metrics'>[],
    championId?: string | null
): string[] {
    return runs.flatMap((run) => {
        const metrics = run.metrics as {
            prediction_date?: string
            per_model?: Record<string, { emitted_role?: string } | undefined>
        } | null
        const perModel = metrics?.per_model ?? {}
        const checked = championId
            ? perModel[championId]?.emitted_role === 'champion'
            : Object.keys(perModel).length > 0
        return run.run_type === 'validation' && run.status === 'completed' && metrics?.prediction_date && checked
            ? [metrics.prediction_date]
            : []
    })
}
