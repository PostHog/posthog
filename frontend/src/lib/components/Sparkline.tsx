import clsx from 'clsx'
import { useCallback, useMemo } from 'react'

import { DefaultTooltip, Sparkline as QuillSparklineChart, useChartTheme } from '@posthog/quill-charts'
import type { Series, TooltipContext, ValueDomain } from '@posthog/quill-charts'

import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { LemonSkeleton } from '../lemon-ui/LemonSkeleton'

export interface SparklineTimeSeries {
    name: string
    values: number[]
    /** Check vars.scss for available colors. @default 'muted' */
    color?: string
    hoverColor?: string
}

export interface SparklineProps {
    /** Either a list of numbers for a muted graph or an array of time series */
    data: number[] | SparklineTimeSeries[]
    /** Check vars.scss for available colors. @default 'muted' */
    color?: string
    colors?: string[]
    /** A name for each time series. */
    name?: string
    names?: string[]
    /** A label for each datapoint. */
    labels?: string[]
    /** @default 'bar' */
    type?: 'bar' | 'line'
    /** A skeleton is shown during loading. */
    loading?: boolean
    /** Render a label for the tooltip. */
    renderLabel?: (label: string) => string
    className?: string
    /** Hide series with zero values from tooltip. @default false */
    hideZerosInTooltip?: boolean
    /** Sort tooltip items by count (descending). @default false */
    sortTooltipByCount?: boolean
    /** Format the per-series tooltip value. Defaults to `humanFriendlyNumber`. */
    renderTooltipValue?: (value: number) => string
    /**
     * X-axis value range to highlight as a translucent box behind the bars. Values are
     * in the x-axis's own units: epoch ms for a time scale (positioned with sub-bar
     * precision), or a label for a category scale. Used to mirror an external selection
     * (e.g. the rows currently visible in a paired virtualized list) onto the chart.
     * Callers pass an already-ordered `xMin <= xMax`; pass `null`/`undefined` to clear.
     */
    highlightedRange?: { xMin: number | string; xMax: number | string } | null
    /**
     * Bar indices that are still being ingested (incomplete). Those bars render with a faded
     * diagonal-hatch fill, and hovering one adds `tooltip` to the hover tooltip. Used to flag the
     * most recent bucket(s) when ingestion hasn't caught up. Pass `null`/`undefined` or an empty
     * `indices` array to clear.
     */
    incompleteBars?: { indices: number[]; tooltip?: string } | null
    /**
     * Let the pointer move onto the tooltip without dismissing it, so a tooltip taller than its
     * max height can be scrolled. Off by default: an interactive tooltip sits over the canvas and
     * would swallow clicks meant for the chart (e.g. clickable markers or drag-to-select).
     */
    interactiveTooltip?: boolean
    /** Pin the value axis instead of auto-scaling to the data, so sparklines in a column stay
     *  comparable to each other. */
    valueDomain?: ValueDomain
}

function normalizeSparklineData(
    data: SparklineProps['data'],
    name?: string,
    names?: string[],
    color?: string,
    colors?: string[]
): SparklineTimeSeries[] {
    const arrayData = Array.isArray(data)
        ? data.length > 0 && typeof data[0] === 'object'
            ? data // array of objects, one per series
            : [data] // array of numbers, turn it into the first series
        : typeof data === 'object'
          ? [data] // first series as an object
          : [[data]] // just a random number... huh
    return arrayData.map((timeseries, index): SparklineTimeSeries => {
        const defaultName =
            names?.[index] || (arrayData.length === 1 ? name || 'Count' : `${name || 'Series'} ${index + 1}`)
        const defaultColor = colors?.[index] || color || 'muted'
        if (typeof timeseries === 'object') {
            if (!Array.isArray(timeseries)) {
                return {
                    name: timeseries.name || defaultName,
                    color: timeseries.color || defaultColor,
                    values: timeseries.values || [],
                }
            }
            return {
                name: defaultName,
                color: defaultColor,
                values: timeseries as number[],
            }
        }
        return {
            name: defaultName,
            color: defaultColor,
            values: timeseries ? [timeseries] : [],
        }
    })
}

/** Width scales with the number of buckets so short sparklines don't stretch their bars. */
function sparklineClassName(dataPointCount: number, className?: string): string {
    return clsx(
        'relative',
        dataPointCount > 16 ? 'w-64' : dataPointCount > 8 ? 'w-48' : dataPointCount > 4 ? 'w-32' : 'w-24',
        className
    )
}

/** Consumers pass vars.scss color names ('success', 'danger', 'muted'); quill takes CSS colors. */
function resolveSparklineColor(color: string | undefined): string {
    const value = color || 'muted'
    return /^(#|rgb|hsl|var\()/.test(value) ? value : getColorVar(value)
}

export function Sparkline({
    data,
    color,
    colors,
    name,
    names,
    labels,
    type = 'bar',
    loading = false,
    renderLabel,
    className,
    hideZerosInTooltip = false,
    sortTooltipByCount = false,
    renderTooltipValue,
    valueDomain,
}: SparklineProps): JSX.Element {
    const theme = useChartTheme()

    const series: Series[] = useMemo(
        () =>
            normalizeSparklineData(data, name, names, color, colors).map((timeseries, index) => ({
                key: `${index}`,
                label: timeseries.name,
                data: timeseries.values,
                color: resolveSparklineColor(timeseries.color),
            })),
        [data, name, names, color, colors]
    )
    const chartLabels = useMemo(() => labels ?? (series[0]?.data ?? []).map((_, i) => `Entry ${i}`), [labels, series])

    const renderTooltip = useCallback(
        (ctx: TooltipContext): JSX.Element => (
            <DefaultTooltip
                {...ctx}
                showHeader={!!labels}
                hideZeroRows={hideZerosInTooltip}
                sortedByValue={sortTooltipByCount}
                valueFormatter={(value) => (renderTooltipValue ?? humanFriendlyNumber)(value)}
                labelFormatter={renderLabel}
            />
        ),
        [labels, hideZerosInTooltip, sortTooltipByCount, renderTooltipValue, renderLabel]
    )

    const finalClassName = sparklineClassName(series[0]?.data.length || 0, className)

    if (loading) {
        return <LemonSkeleton className={finalClassName} />
    }
    if (data === undefined || data.length === 0) {
        return <div className={finalClassName} />
    }
    return (
        <div className={finalClassName}>
            <QuillSparklineChart
                series={series}
                labels={chartLabels}
                theme={theme}
                type={type}
                valueDomain={valueDomain}
                fill
                className="h-full"
                tooltip={renderTooltip}
            />
        </div>
    )
}
