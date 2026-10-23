import { useValues } from 'kea'
import { Fragment, useMemo } from 'react'

import { TimeSeriesLineChart, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { bucketHeadline, formatBucket, hourTick, percentTrend, toChartValues } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

const MEDIAN_KEY = '__median'

export function EvaluationPassRateCompareChart({ colors }: { colors: Map<string, string> }): JSX.Element {
    const theme = useChartTheme()
    const {
        overview,
        measuredPassRateRows: measured,
        compareListRows,
        buckets,
        timezone,
        interval,
    } = useValues(evaluationsOverviewLogic)

    // Only the picked evaluations draw, so every line on the chart is one the list shows as picked.
    const drawn = useMemo(
        () => ({ measuredCount: measured.length, picked: compareListRows.filter((row) => colors.has(row.id)) }),
        [measured, compareListRows, colors]
    )

    const medianTrend = useMemo(() => toChartValues(overview?.passRateOverview.medianTrend ?? []), [overview])

    const series = useMemo<Series[]>(() => {
        return [
            ...drawn.picked.map((row) => ({
                key: row.id,
                label: row.name,
                data: percentTrend(row),
                color: colors.get(row.id),
                points: { radius: 2.5 },
            })),
            // A median of one evaluation is that evaluation, so the extra line would only hide it.
            ...(drawn.measuredCount > 1
                ? [
                      {
                          key: MEDIAN_KEY,
                          label: 'Median pass rate',
                          data: medianTrend,
                          color: getColorVar('color-text-primary'),
                          stroke: { pattern: [6, 4] },
                      },
                  ]
                : []),
        ]
    }, [drawn, colors, medianTrend])

    const config = useMemo<TimeSeriesLineChartConfig>(() => {
        // The median covers every measured evaluation, not only the picked ones, so it can sit below all of them.
        const finite = series.flatMap((entry) => entry.data).filter(Number.isFinite)
        const floor = finite.length > 0 ? Math.max(0, Math.floor((Math.min(...finite) - 5) / 10) * 10) : 0
        return {
            xAxis: { timezone, interval, ...(interval === 'hour' ? { tickFormatter: hourTick } : {}) },
            yAxis: { format: 'percentage', showGrid: true },
            // Straight segments, because a curve invents values between buckets and overshoots on sparse ones.
            curve: 'linear',
            valueDomain: { min: floor, max: 100 },
            showCrosshair: true,
        }
    }, [series, timezone, interval])

    const tooltip = (ctx: TooltipContext): JSX.Element => {
        const median = medianTrend[ctx.dataIndex]
        const picked = drawn.picked.filter((row) => row.trend.values[ctx.dataIndex] !== null)
        return (
            <TooltipSurface>
                <div className="font-semibold mb-1">{formatBucket(String(ctx.label), interval)}</div>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0.5">
                    {picked.map((row) => (
                        <Fragment key={row.id}>
                            <span className="flex items-center gap-2 min-w-0">
                                <TooltipSwatch color={colors.get(row.id) ?? ''} />
                                <span className="truncate max-w-72">{row.name}</span>
                            </span>
                            {/* The value stays short, so the name gets the rest of the tooltip's fixed width. */}
                            <span className="text-right whitespace-nowrap tabular-nums">
                                <strong>{bucketHeadline(row, ctx.dataIndex)}</strong>
                                <span className="text-secondary">{` · ${humanFriendlyNumber(row.trend.volume[ctx.dataIndex] ?? 0)}`}</span>
                            </span>
                        </Fragment>
                    ))}
                    {drawn.measuredCount > 1 && Number.isFinite(median) && (
                        <>
                            <span className="mt-1 pt-1 border-t border-current/25">Median pass rate</span>
                            <strong className="mt-1 pt-1 border-t border-current/25 text-right whitespace-nowrap tabular-nums">
                                {`${median.toFixed(1)}%`}
                            </strong>
                        </>
                    )}
                </div>
            </TooltipSurface>
        )
    }

    return (
        <div className="h-96 min-w-0 flex flex-col">
            <TimeSeriesLineChart series={series} labels={buckets} theme={theme} config={config} tooltip={tooltip} />
        </div>
    )
}
