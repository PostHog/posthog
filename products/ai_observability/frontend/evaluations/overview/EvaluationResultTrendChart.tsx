import { useValues } from 'kea'
import { useMemo } from 'react'

import { TimeSeriesComboChart, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { Series, TimeSeriesComboChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { formatBucket, hourTick, toChartValues, trackedCategory } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

const VOLUME_KEY = 'volume'
const VOLUME_CEILING_KEY = 'volume-ceiling'
/** Volume bars use at most this share of the plot height, so they read as context behind the line. */
const VOLUME_HEIGHT_SHARE = 1 / 4

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

export function EvaluationResultTrendChart({ row }: { row: EvaluationResultApi }): JSX.Element {
    const theme = useChartTheme()
    const { buckets, timezone, interval } = useValues(evaluationsOverviewLogic)
    const { summary, trend } = row
    const isScore = summary.kind === 'score'
    const label = trackedCategory(row)?.label ?? HEADLINE_LABELS[summary.kind]
    const values = useMemo(() => toChartValues(trend.values), [trend])

    const series = useMemo<Series[]>(() => {
        return [
            {
                key: VOLUME_KEY,
                label: 'Graded',
                data: trend.volume,
                type: 'bar',
                yAxisId: VOLUME_KEY,
                color: withAlpha(getColorVar('muted'), 0.3),
            },
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
            {
                key: 'headline',
                label,
                // NaN leaves a gap, so a bucket with no graded results never reads as a measured 0%.
                data: values,
                type: 'line',
                color: theme.colors[0],
                points: { radius: 3 },
            },
        ]
    }, [trend, values, label, theme])

    const config = useMemo<TimeSeriesComboChartConfig>(() => {
        const finite = values.filter(Number.isFinite)
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
        }
    }, [isScore, summary, values, timezone, interval])

    const tooltip = (ctx: TooltipContext): JSX.Element => {
        const value = values[ctx.dataIndex]
        const line = ctx.seriesData.find((entry) => entry.series.key === 'headline')
        return (
            <TooltipSurface>
                <div className="font-semibold">{formatBucket(String(ctx.label), interval)}</div>
                {Number.isFinite(value) ? (
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
                <div className="flex items-center gap-2 opacity-70">
                    <span>Graded results</span>
                    <span className="ml-auto tabular-nums">
                        {humanFriendlyNumber(trend.volume[ctx.dataIndex] ?? 0)}
                    </span>
                </div>
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
                />
            </div>
            <div className="text-xs text-secondary">{`Shaded bars show how many results were graded each ${interval}.`}</div>
        </div>
    )
}
