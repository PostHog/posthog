import { useMemo } from 'react'

import { TimeSeriesComboChart, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { Series, TimeSeriesComboChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { midEllipsis } from 'lib/utils/strings'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import {
    type BucketInterval,
    formatBucket,
    hourTick,
    passFailCounts,
    toChartValues,
    trackedCategory,
} from './evaluationOverviewDisplay'

// The volume axis is hidden, so the chart needs no room for labels on the right.
const CHART_MARGINS = { right: 16 }
// Fits max-w-60 and cuts in the middle, so the end that tells similar labels apart stays visible.
const LABEL_CHARS = 28
const VOLUME_KEY = 'volume'
const PASSED_KEY = 'passed'
const FAILED_KEY = 'failed'
const VOLUME_CEILING_KEY = 'volume-ceiling'
/** Volume bars use at most this share of the plot height, so they read as context behind the line. */
const VOLUME_HEIGHT_SHARE = 1 / 3

const HEADLINE_LABELS: Record<EvaluationResultApi['summary']['kind'], string> = {
    pass_rate: 'Pass rate',
    score: 'Mean score',
    sentiment: 'Negative share',
    categories: 'Share with the tracked label',
}

/** Canvas colors cannot read CSS variables, so resolve the token and add transparency. */
function withAlpha(color: string, alpha: number): string {
    const hex = color.startsWith('#') && color.length === 7 ? color : null
    return hex
        ? `${hex}${Math.round(alpha * 255)
              .toString(16)
              .padStart(2, '0')}`
        : color
}

/** One value of a breakdown property, aligned with the buckets. NaN marks a bucket where it had nothing graded. */
export interface TrendBreakdownSeries {
    key: string
    label: string
    values: number[]
    graded: number[]
}

/** The overall line uses the theme's first color, so breakdown lines start at the second. */
function breakdownColor(colors: string[], index: number): string {
    return colors[(index + 1) % colors.length]
}

export function EvaluationResultTrendChart({
    row,
    buckets,
    interval,
    timezone,
    onSelectBucket,
    footer,
    breakdown,
}: {
    row: EvaluationResultApi
    buckets: string[]
    interval: BucketInterval
    timezone: string
    /** Called with the clicked bucket. Without it the chart is not clickable. */
    onSelectBucket?: (bucket: string) => void
    footer?: React.ReactNode
    breakdown?: TrendBreakdownSeries[] | null
}): JSX.Element {
    const theme = useChartTheme()
    const { summary, trend } = row
    const isScore = summary.kind === 'score'
    const label = trackedCategory(row)?.label ?? HEADLINE_LABELS[summary.kind]
    const values = useMemo(() => toChartValues(trend.values), [trend])
    const counts = useMemo(() => passFailCounts(row), [row])

    const series = useMemo<Series[]>(() => {
        // Pass rates split the bars into passed and failed, because a rate can drop while failures stay flat.
        const volumeBars: Series[] = counts
            ? [
                  {
                      key: PASSED_KEY,
                      label: 'Passed',
                      data: counts.passed,
                      type: 'bar',
                      yAxisId: VOLUME_KEY,
                      color: withAlpha(getColorVar('success'), 0.35),
                  },
                  {
                      key: FAILED_KEY,
                      label: 'Failed',
                      data: counts.failed,
                      type: 'bar',
                      yAxisId: VOLUME_KEY,
                      color: withAlpha(getColorVar('danger'), 0.35),
                  },
              ]
            : [
                  {
                      key: VOLUME_KEY,
                      label: 'Graded',
                      data: trend.volume,
                      type: 'bar',
                      yAxisId: VOLUME_KEY,
                      color: withAlpha(getColorVar('muted'), 0.3),
                  },
              ]
        return [
            ...volumeBars,
            // The combo chart ignores axis bounds, so an invisible line at the ceiling stretches the volume axis
            // and keeps the real bars in the bottom part of the plot.
            {
                key: VOLUME_CEILING_KEY,
                label: '',
                data: trend.volume.map(() => Math.max(1, ...trend.volume) / VOLUME_HEIGHT_SHARE),
                type: 'line',
                yAxisId: VOLUME_KEY,
                color: 'transparent',
                visibility: { tooltip: false, total: false, valueLabel: false },
            },
            ...(breakdown
                ? breakdown.map(
                      (entry, index): Series => ({
                          key: `breakdown-${entry.key}`,
                          label: entry.label,
                          data: entry.values,
                          type: 'line',
                          color: breakdownColor(theme.colors, index),
                          points: { radius: 3 },
                      })
                  )
                : [
                      {
                          key: 'headline',
                          label,
                          // NaN leaves a gap, so a bucket with no graded results never reads as a measured 0%.
                          data: values,
                          type: 'line' as const,
                          color: theme.colors[0],
                          points: { radius: 3 },
                      },
                  ]),
        ]
    }, [trend, values, counts, label, theme, breakdown])

    const config = useMemo<TimeSeriesComboChartConfig>(() => {
        const finite = (breakdown ? breakdown.flatMap((entry) => entry.values) : values).filter(Number.isFinite)
        // Zoom in when every point sits high, and let the axis labels say so.
        const floor = finite.length > 0 ? Math.max(0, Math.floor((Math.min(...finite) - 10) / 10) * 10) : 0
        const scale = summary.kind === 'score' ? summary.score?.scale : null
        return {
            xAxis: { timezone, interval, ...(interval === 'hour' ? { tickFormatter: hourTick } : {}) },
            // Straight segments, because a curve invents values between buckets and overshoots on sparse ones.
            curve: 'linear',
            yAxis: [
                isScore
                    ? { id: 'left', showGrid: true, decimalPlaces: 2 }
                    : { id: 'left', showGrid: true, format: 'percentage' },
                { id: VOLUME_KEY, position: 'right', hide: true },
            ],
            valueDomain: isScore ? (scale ? { min: scale.min, max: scale.max } : undefined) : { min: floor, max: 100 },
            margins: CHART_MARGINS,
        }
    }, [isScore, summary, values, timezone, interval, breakdown])

    const tooltip = (ctx: TooltipContext): JSX.Element => {
        const value = values[ctx.dataIndex]
        const line = ctx.seriesData.find((entry) => entry.series.key === 'headline')
        return (
            <TooltipSurface>
                <div className="font-semibold">{formatBucket(String(ctx.label), interval)}</div>
                {breakdown ? (
                    breakdown.map((entry, index) =>
                        Number.isFinite(entry.values[ctx.dataIndex]) ? (
                            <div key={entry.key} className="flex items-center gap-2 mt-1">
                                <TooltipSwatch color={breakdownColor(theme.colors, index)} />
                                <span className="truncate max-w-60">{midEllipsis(entry.label, LABEL_CHARS)}</span>
                                <strong className="ml-auto tabular-nums">
                                    {isScore
                                        ? entry.values[ctx.dataIndex].toFixed(2)
                                        : `${entry.values[ctx.dataIndex].toFixed(1)}%`}
                                </strong>
                                <span className="opacity-70 tabular-nums">
                                    {`${humanFriendlyNumber(entry.graded[ctx.dataIndex] ?? 0)} graded`}
                                </span>
                            </div>
                        ) : null
                    )
                ) : Number.isFinite(value) ? (
                    <div className="flex items-center gap-2 mt-1">
                        {line && <TooltipSwatch color={line.color} />}
                        <span>{label}</span>
                        <strong className="ml-auto tabular-nums">
                            {isScore ? value.toFixed(2) : `${value.toFixed(1)}%`}
                        </strong>
                    </div>
                ) : (
                    <div className="mt-1 opacity-70">No graded results</div>
                )}
                {counts ? (
                    <>
                        <div className="flex items-center gap-2 opacity-70">
                            <span>Passed</span>
                            <span className="ml-auto tabular-nums">
                                {humanFriendlyNumber(counts.passed[ctx.dataIndex] ?? 0)}
                            </span>
                        </div>
                        <div className="flex items-center gap-2 opacity-70">
                            <span>Failed</span>
                            <span className="ml-auto tabular-nums">
                                {humanFriendlyNumber(counts.failed[ctx.dataIndex] ?? 0)}
                            </span>
                        </div>
                    </>
                ) : (
                    <div className="flex items-center gap-2 opacity-70">
                        <span>Graded results</span>
                        <span className="ml-auto tabular-nums">
                            {humanFriendlyNumber(trend.volume[ctx.dataIndex] ?? 0)}
                        </span>
                    </div>
                )}
            </TooltipSurface>
        )
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="h-56 min-w-0 flex flex-col">
                <TimeSeriesComboChart
                    series={series}
                    labels={buckets}
                    theme={theme}
                    config={config}
                    tooltip={tooltip}
                    onPointClick={
                        onSelectBucket
                            ? ({ dataIndex }) => buckets[dataIndex] && onSelectBucket(buckets[dataIndex])
                            : undefined
                    }
                />
            </div>
            <div className="text-xs text-secondary">
                {counts
                    ? `Bars show how many results passed and failed each ${interval}.`
                    : `Shaded bars show how many results were graded each ${interval}.`}
                {onSelectBucket ? ` Click a${interval === 'hour' ? 'n' : ''} ${interval} to see its runs.` : ''}
            </div>
            {breakdown && breakdown.length > 0 && (
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                    {breakdown.map((entry, index) => (
                        <span key={entry.key} className="flex items-center gap-1 min-w-0">
                            <span
                                className="inline-block size-2 shrink-0 rounded-full"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: breakdownColor(theme.colors, index) }}
                            />
                            <span className="truncate max-w-60" title={entry.label}>
                                {midEllipsis(entry.label, LABEL_CHARS)}
                            </span>
                        </span>
                    ))}
                </div>
            )}
            {footer}
        </div>
    )
}
