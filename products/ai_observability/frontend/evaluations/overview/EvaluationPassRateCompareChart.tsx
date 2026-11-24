import { useValues } from 'kea'
import { Fragment, useMemo } from 'react'

import { TimeSeriesLineChart, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { midEllipsis } from 'lib/utils/strings'

import { EvaluationBackfillHint } from './EvaluationBackfillHint'
import { bucketHeadline, formatBucket, hasIsolatedPoints, hourTick, percentTrend } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

// Fits the tooltip name column and cuts in the middle, so the end that tells similar names apart stays visible.
const TOOLTIP_NAME_CHARS = 30

export function EvaluationPassRateCompareChart({ colors }: { colors: Map<string, string> }): JSX.Element {
    const theme = useChartTheme()
    const { compareListRows, buckets, timezone, interval } = useValues(evaluationsOverviewLogic)

    // Only the picked evaluations draw, so every line on the chart is one the list shows as picked.
    const picked = useMemo(() => compareListRows.filter((row) => colors.has(row.id)), [compareListRows, colors])

    const series = useMemo<Series[]>(
        () =>
            picked.map((row) => ({
                key: row.id,
                label: row.name,
                data: percentTrend(row),
                color: colors.get(row.id),
                points: { radius: 2.5 },
            })),
        [picked, colors]
    )

    const config = useMemo<TimeSeriesLineChartConfig>(() => {
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
        const withValue = picked.filter((row) => row.trend.values[ctx.dataIndex] !== null)
        return (
            <TooltipSurface>
                <div className="font-semibold mb-1">{formatBucket(String(ctx.label), interval)}</div>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0.5">
                    {withValue.map((row) => (
                        <Fragment key={row.id}>
                            <span className="flex items-center gap-2 min-w-0">
                                <TooltipSwatch color={colors.get(row.id) ?? ''} />
                                <span className="truncate max-w-72">{midEllipsis(row.name, TOOLTIP_NAME_CHARS)}</span>
                            </span>
                            {/* The value stays short, so the name gets the rest of the tooltip's fixed width. */}
                            <span className="text-right whitespace-nowrap tabular-nums">
                                <strong>{bucketHeadline(row, ctx.dataIndex)}</strong>
                                <span className="text-secondary">{` · ${humanFriendlyNumber(row.trend.volume[ctx.dataIndex] ?? 0)}`}</span>
                            </span>
                        </Fragment>
                    ))}
                </div>
            </TooltipSurface>
        )
    }

    const sparse = picked.filter(hasIsolatedPoints)
    return (
        <>
            <div className="h-96 min-w-0 flex flex-col">
                <TimeSeriesLineChart series={series} labels={buckets} theme={theme} config={config} tooltip={tooltip} />
            </div>
            {sparse.map((row) => (
                <EvaluationBackfillHint key={row.id} row={row} source="compare_chart" named />
            ))}
        </>
    )
}
