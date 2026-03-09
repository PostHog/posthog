import { hexToRGBA } from 'lib/utils'

import type { AxisConfig, GoalLine, LineProps, Series } from '../types'

const MAX_SERIES = 50

// ------------------------------------------------------------------
// Input types — the consumer maps their API response to these
// ------------------------------------------------------------------

export interface DataSeries {
    label: string
    data: number[]
    color: string
    /** Any extra data the consumer wants passed through to click/tooltip handlers untouched. */
    meta?: Record<string, unknown>

    /** When true, series is from a previous-period comparison and rendered dashed/dimmed. */
    isComparison?: boolean
    /** Lifecycle status — if set, `statusColor` must resolve it to a color. */
    status?: string
    /** If true, this series is hidden and will be excluded from the output. */
    hidden?: boolean
}

export interface StatisticalOverlays {
    confidenceIntervals?: {
        enabled: boolean
        level: number
        /** Return [lower[], upper[]] bounds for the raw data. */
        compute: (data: number[], level: number) => [number[], number[]]
    }
    movingAverage?: {
        enabled: boolean
        intervals: number
        /** Return smoothed data. */
        compute: (data: number[], intervals: number) => number[]
    }
    trendLines?: boolean
}

export interface BuildLineSeriesOptions {
    series: DataSeries[]

    display?: {
        type?: 'line' | 'bar'
        area?: boolean
    }

    transforms?: {
        /** Replace zeros with epsilon for log-scale display. */
        logScale?: boolean
        /** Normalize values as percentages of total count (for stickiness). */
        percentOfTotal?: (data: number[], count: number) => number[]
    }

    axes?: {
        /** When true, alternate series between left/right y-axes. */
        multipleYAxes?: boolean
    }

    statistics?: StatisticalOverlays

    /** Resolve a status string to a color (for lifecycle charts). */
    statusColor?: (status: string) => string
}

export interface BuildLineSeriesResult {
    series: Series[]
}

/**
 * Converts an array of `DataSeries` into hog-charts `Series[]`,
 * applying display transforms, statistical overlays, and comparison styling.
 *
 * This is a pure function — no side effects, no DOM, no React.
 */
export function buildLineSeries(opts: BuildLineSeriesOptions): BuildLineSeriesResult {
    const result: Series[] = []
    const displayType = opts.display?.type ?? 'line'
    const isArea = opts.display?.area ?? false

    for (const [index, ds] of opts.series.entries()) {
        if (ds.hidden) {
            continue
        }
        if (result.length >= MAX_SERIES) {
            break
        }

        let data = ds.data

        // Log-scale: replace zeros with tiny epsilon so log(0) doesn't blow up
        if (opts.transforms?.logScale) {
            data = data.map((v) => (v === 0 ? 1e-10 : v))
        }

        // Stickiness-style percent-of-total normalization
        if (opts.transforms?.percentOfTotal) {
            const count = ds.meta?.count as number | undefined
            if (count !== undefined) {
                data = opts.transforms.percentOfTotal(data, count)
            }
        }

        // Color: status color > comparison dimming > raw color
        let color = ds.color
        if (ds.status && opts.statusColor) {
            color = opts.statusColor(ds.status)
        } else if (ds.isComparison) {
            color = `${ds.color}80`
        }

        const yAxisPosition = opts.axes?.multipleYAxes && index > 0 && index % 2 !== 0 ? 'right' : 'left'

        result.push({
            label: ds.label,
            data,
            color,
            displayType,
            yAxisPosition: yAxisPosition as 'left' | 'right',
            fill: isArea,
            trendLine: opts.statistics?.trendLines,
            lineStyle: ds.isComparison ? 'dashed' : undefined,
            hideFromTooltip: false,
            meta: ds.meta ?? {},
        })

        // Confidence intervals — two auxiliary series (lower bound + filled upper bound)
        const ci = opts.statistics?.confidenceIntervals
        if (ci?.enabled) {
            const [lower, upper] = ci.compute(ds.data, ci.level / 100)
            result.push({
                label: `${ds.label} (CI lower)`,
                data: lower,
                color: ds.color,
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
            result.push({
                label: `${ds.label} (CI upper)`,
                data: upper,
                color: hexToRGBA(ds.color, 0.2),
                fill: true,
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
        }

        // Moving average — dashed auxiliary series
        const ma = opts.statistics?.movingAverage
        if (ma?.enabled) {
            const smoothed = ma.compute(ds.data, ma.intervals)
            result.push({
                label: `${ds.label} (Moving avg)`,
                data: smoothed,
                color: ds.color,
                lineStyle: 'dashed',
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
        }
    }

    return { series: result }
}

// ------------------------------------------------------------------
// Y-axis builder
// ------------------------------------------------------------------

export function buildYAxis(
    options: {
        logScale?: boolean
        percentStacked?: boolean
        multipleYAxes?: boolean
        seriesCount?: number
    } = {}
): LineProps['yAxis'] {
    const base: AxisConfig = {
        startAtZero: !options.logScale,
        scale: options.logScale ? 'logarithmic' : 'linear',
        gridLines: true,
        format: options.percentStacked ? 'percent' : undefined,
    }

    if (options.multipleYAxes && (options.seriesCount ?? 0) > 1) {
        return [base, { ...base, gridLines: false }]
    }

    return base
}

// ------------------------------------------------------------------
// Goal-line builder
// ------------------------------------------------------------------

export interface GoalLineInput {
    value: number
    label?: string | null
    color?: string | null
}

export function buildGoalLines(inputs: GoalLineInput[]): GoalLine[] {
    return inputs.map((gl) => ({
        value: gl.value,
        label: gl.label ?? undefined,
        color: gl.color ?? undefined,
        style: 'dashed' as const,
    }))
}
