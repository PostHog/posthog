import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { AttentionReasonsEnumApi, CategoryCountApi, EvaluationResultApi } from '../../generated/api.schemas'
import { statusReasonLabel } from '../statusDisplay'
import type { EvaluationStatusReason } from '../types'

export const RATE_LIMITED_MESSAGE = 'Too many requests, try again in a moment.'

export function formatPercent(value: number): string {
    return Number.isFinite(value) ? `${value.toFixed(1)}%` : '-'
}

export function formatPoints(value: number): string {
    return Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(1)} pp` : '-'
}

export type BucketInterval = 'hour' | 'day'

/**
 * A bucket start for tooltips, read from its own text. Buckets carry the project's offset, so reading the date and
 * time off the string shows project time whatever the viewer's timezone is.
 */
export function formatBucket(label: string, interval: BucketInterval): string {
    const day = dayjs(label.slice(0, 10)).format('ddd, MMM D')
    return interval === 'hour' ? `${day}, ${label.slice(11, 16)}` : day
}

/** A short bucket start for the ends of an axis, for example "Oct 22" or "Oct 22, 14:00". */
export function formatBucketShort(label: string, interval: BucketInterval): string {
    const day = dayjs(label.slice(0, 10)).format('MMM D')
    return interval === 'hour' ? `${day}, ${label.slice(11, 16)}` : day
}

/** Charts take NaN for a missing point, where the API sends null. */
export function toChartValues(values: (number | null)[]): number[] {
    return values.map((value) => (value === null ? NaN : value))
}

function share(part: number, whole: number): number {
    return whole > 0 ? (part / whole) * 100 : NaN
}

/** The category a categorical row's trend follows. Labels can repeat, so it is found by key. */
export function trackedCategory(row: EvaluationResultApi): CategoryCountApi | undefined {
    return row.summary.kind === 'categories'
        ? row.summary.categories.find((entry) => entry.key === row.trackedCategory)
        : undefined
}

export function passRate(row: EvaluationResultApi): number {
    const { summary } = row
    return summary.kind === 'pass_rate' ? share(summary.passed, summary.passed + summary.failed) : NaN
}

/**
 * A row's period result on a 0-100 scale, so every evaluation type can share one axis. Pass rates, negative
 * sentiment and label shares are already percentages. Scores become their position on the configured scale.
 */
export function percentValue(row: EvaluationResultApi): number {
    const { summary } = row
    switch (summary.kind) {
        case 'pass_rate':
            return passRate(row)
        case 'sentiment':
            return share(summary.negative, summary.positive + summary.neutral + summary.negative)
        case 'categories': {
            const category = trackedCategory(row)
            return category ? share(category.count, row.gradedCount) : NaN
        }
        case 'score':
            return summary.score?.scale
                ? share(summary.score.mean - summary.score.scale.min, summary.score.scale.max - summary.score.scale.min)
                : NaN
    }
}

/** The same 0-100 scale as `percentValue`, for each day of the trend. */
export function percentTrend(row: EvaluationResultApi): number[] {
    const values = toChartValues(row.trend.values)
    const { summary } = row
    if (summary.kind !== 'score') {
        return values
    }
    const scale = summary.score?.scale
    return values.map((value) => (scale ? share(value - scale.min, scale.max - scale.min) : NaN))
}

/** Short result for lists and legends, for example "92.5%", "18% negative" or "Mean 0.71". */
export function compactHeadline(row: EvaluationResultApi): string {
    const { summary } = row
    const value = percentValue(row)
    switch (summary.kind) {
        case 'pass_rate':
            return formatPercent(value)
        case 'score':
            return summary.score ? `Mean ${summary.score.mean.toFixed(2)}` : '-'
        case 'sentiment':
            return Number.isFinite(value) ? `${Math.round(value)}% negative` : '-'
        case 'categories':
            return Number.isFinite(value) ? `${trackedCategory(row)?.label} ${Math.round(value)}%` : '-'
    }
}

/** What one bucket means for this row, for tooltips. */
export function describeBucket(row: EvaluationResultApi, index: number): string {
    const value = row.trend.values[index]
    const volume = row.trend.volume[index] ?? 0
    if (value == null) {
        return 'No graded results'
    }
    switch (row.summary.kind) {
        case 'pass_rate':
            return `${formatPercent(value)} passed, ${volume} graded`
        case 'score':
            return `Mean ${value.toFixed(2)}, ${volume} graded`
        case 'sentiment':
            return `${Math.round(value)}% negative, ${volume} classified`
        case 'categories':
            return `${trackedCategory(row)?.label} on ${Math.round(value)}%, ${volume} classified`
    }
}

/** One bucket's result without words, for the compact compare tooltip, for example "82.1%" or "Mean 3.80". */
export function bucketHeadline(row: EvaluationResultApi, index: number): string | null {
    const value = row.trend.values[index]
    if (value == null) {
        return null
    }
    switch (row.summary.kind) {
        case 'pass_rate':
            return formatPercent(value)
        case 'score':
            return `Mean ${value.toFixed(2)}`
        case 'sentiment':
            return `${Math.round(value)}% negative`
        case 'categories':
            return `${trackedCategory(row)?.label} ${Math.round(value)}%`
    }
}

/** The day of the latest graded run in the project's timezone, which the chart's buckets also use. */
export function lastResultDay(row: EvaluationResultApi, timezone: string): string | null {
    return row.lastRunAt ? dayjs(row.lastRunAt).tz(timezone).format('MMM D') : null
}

export function describeAttention(row: EvaluationResultApi, timezone: string): string | null {
    const [reason] = row.attentionReasons
    switch (reason) {
        case 'errored':
            return statusReasonLabel(row.statusReason as EvaluationStatusReason | null)
        case 'silent': {
            // The read starts at the previous period, so a missing last run means nothing in that window, not never.
            const day = lastResultDay(row, timezone)
            return day ? `Enabled, but no results since ${day}` : 'Enabled, but no results in this range'
        }
        case 'worse': {
            const rate = percentValue(row)
            const change = row.change?.value ?? NaN
            return row.summary.kind === 'sentiment'
                ? `Negative share rose ${Math.abs(change).toFixed(1)} pp to ${Math.round(rate)}%`
                : `Fell ${Math.abs(change).toFixed(1)} pp, from ${formatPercent(rate - change)} to ${formatPercent(rate)}`
        }
        default:
            return null
    }
}

export const ATTENTION_LABELS: Record<AttentionReasonsEnumApi, string> = {
    errored: 'Errored',
    silent: 'No recent results',
    worse: 'Worse than before',
}

const METHOD_LABELS: Record<string, string> = {
    llm_judge: 'LLM judge',
    hog: 'Hog',
    sentiment: 'Sentiment',
}

export function methodLabel(row: EvaluationResultApi): string {
    return METHOD_LABELS[row.evaluationType] ?? row.evaluationType
}

export function outputTypeLabel(row: EvaluationResultApi): string | null {
    const { summary } = row
    switch (summary.kind) {
        case 'pass_rate':
            return row.outputType === 'numeric'
                ? 'Numeric'
                : row.outputType === 'categorical'
                  ? 'Categorical'
                  : 'Boolean'
        case 'score':
            return 'Numeric'
        case 'categories':
            return summary.multiple ? 'Multiple labels' : 'Single label'
        case 'sentiment':
            return null
    }
}

/** The result in words, for the table, for example "92.5% passed" or "Billing 42% · Bug report 33%". */
export function resultHeadline(row: EvaluationResultApi): string {
    const { summary } = row
    switch (summary.kind) {
        case 'pass_rate':
            return `${formatPercent(passRate(row))} passed`
        case 'score':
            return summary.score
                ? `Mean ${summary.score.mean.toFixed(2)}${summary.score.scale ? ` on ${summary.score.scale.min}-${summary.score.scale.max}` : ''}`
                : '-'
        case 'categories':
            return summary.categories
                .slice(0, 2)
                .map((category) => `${category.label} ${Math.round(share(category.count, row.gradedCount))}%`)
                .join(' · ')
        case 'sentiment':
            return compactHeadline(row)
    }
}

export function resultEvidence(row: EvaluationResultApi): string {
    const { summary } = row
    const parts =
        summary.kind === 'pass_rate'
            ? [`${humanFriendlyNumber(summary.passed)} / ${humanFriendlyNumber(row.gradedCount)} graded`]
            : [`${humanFriendlyNumber(row.gradedCount)} ${summary.kind === 'score' ? 'graded' : 'classified'}`]
    if (row.notApplicableCount > 0) {
        parts.push(`${humanFriendlyNumber(row.notApplicableCount)} N/A`)
    }
    return parts.join(' · ')
}

/** Whether the row has at least one day the compare chart can draw. */
export function isChartable(row: EvaluationResultApi): boolean {
    return row.gradedCount > 0 && percentTrend(row).some(Number.isFinite)
}

/** Hourly axes label every third hour, so midnight always gets a tick. */
const HOUR_TICK_STEP = 3

/**
 * Axis ticks for hourly buckets: the time every few hours, and the date at midnight so a range across two days
 * says where the second one starts. Read from the bucket text, which carries the project's offset.
 */
export function hourTick(label: string): string | null {
    const hour = Number(label.slice(11, 13))
    if (hour % HOUR_TICK_STEP !== 0) {
        return null
    }
    return hour === 0 ? dayjs(label.slice(0, 10)).format('MMM D') : label.slice(11, 16)
}
