import clsx from 'clsx'
import { useCallback, useMemo } from 'react'

import { LemonColorGlyph } from '@posthog/lemon-ui'
import { PieChart, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { PieChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { formatDataWithSettings } from '../../dataVisualizationLogic'
import { LineGraphProps } from './LineGraph'
import { buildPieSeries, buildPieSlices, formatPieSliceCount } from './sqlPieGraphAdapter'

const handleChartError = makeChartErrorHandler('sql-pie-chart')

/**
 * SQL pie graph on @posthog/quill-charts' {@link PieChart}, gated behind the
 * `product-analytics-quill-sql-charts` flag (see {@link sqlChartComponentFor}). The chart core lives
 * in quill; the aggregation total and side legend stay here as chrome, matching the legacy wrapper.
 */
export const SqlPieGraph = ({
    xData,
    yData,
    chartSettings,
    presetChartHeight,
    className,
}: LineGraphProps): JSX.Element => {
    const theme = useChartTheme()

    const slices = useMemo(() => buildPieSlices(xData, yData), [xData, yData])
    const formattingSettings = yData[0]?.settings
    const series = useMemo(() => buildPieSeries(slices), [slices])
    const total = useMemo(() => slices.reduce((sum, slice) => sum + slice.value, 0), [slices])

    const showLegend = chartSettings.showLegend ?? false
    // Unset means an existing chart from before the labels option — keep showing values. New pies
    // are stamped with 'labels' when the type is picked (see dataVisualizationLogic).
    const sliceContent = chartSettings.pie?.sliceContent ?? 'values'
    // The total is a sum-of-values readout, so default it on only when slices show values.
    // `showPieTotal` is the legacy top-level toggle — honor it for charts saved before `pie`.
    const showPieTotal = chartSettings.pie?.showTotal ?? chartSettings.showPieTotal ?? sliceContent === 'values'
    const asPercent = (chartSettings.pie?.valueDisplay ?? 'absolute') === 'percentage'

    const absoluteFormatter = useCallback(
        (value: number) => String(formatDataWithSettings(value, formattingSettings) ?? value),
        [formattingSettings]
    )

    // `isPercent` makes the chart render on-slice values and tooltips as a share of the total; the
    // total below the chart and the absolute legend line keep using the raw value formatter.
    // Labels sit toward the rim (on the wider part of each wedge) and skip slices under 10% so a
    // long tail of thin slices doesn't pile labels up at the center.
    const pieConfig: PieChartConfig = useMemo(
        () => ({
            showLabelOnSlice: sliceContent === 'labels',
            showValueOnSlice: sliceContent === 'values',
            isPercent: asPercent,
            labelRadiusRatio: 0.72,
            minSlicePercentForLabel: 0.1,
        }),
        [sliceContent, asPercent]
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext) => {
            const entry = ctx.seriesData[0]
            if (!entry) {
                return null
            }
            return (
                <TooltipSurface>
                    <div className="flex items-center gap-2">
                        <TooltipSwatch color={entry.color} />
                        <span className="font-semibold">{entry.series.label}</span>
                        <strong className="ml-auto">
                            {formatPieSliceCount(entry.value, total, formattingSettings, asPercent)}
                        </strong>
                    </div>
                </TooltipSurface>
            )
        },
        [total, formattingSettings, asPercent]
    )

    if (!slices.length) {
        return (
            <div className={clsx(className, 'rounded bg-surface-primary flex flex-1 items-center justify-center p-6')}>
                <span className="text-secondary text-sm">Pie charts require at least one positive value.</span>
            </div>
        )
    }

    const chart = (
        <PieChart
            series={series}
            theme={theme}
            config={pieConfig}
            tooltip={renderTooltip}
            valueFormatter={absoluteFormatter}
            dataAttr="sql-pie-chart"
            onError={handleChartError}
        />
    )

    const totalDisplay = showPieTotal ? (
        <div className="pt-4 text-center shrink-0">
            <div className="text-5xl font-bold">{absoluteFormatter(total)}</div>
        </div>
    ) : null

    const legend = showLegend ? (
        <div className="w-full xl:w-80 shrink-0 border border-border rounded bg-surface-secondary overflow-visible xl:overflow-auto">
            <div className="divide-y divide-border">
                {slices.map((slice) => {
                    const percent = total > 0 ? ((slice.value / total) * 100).toFixed(1) : '0.0'

                    return (
                        <div key={slice.label} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                            <div className="flex items-center gap-2 min-w-0">
                                <LemonColorGlyph color={slice.color} className="shrink-0" />
                                <span className="truncate">{slice.label}</span>
                            </div>
                            <div className="text-right shrink-0">
                                <div className="font-semibold">
                                    {asPercent ? `${percent}%` : absoluteFormatter(slice.value)}
                                </div>
                                <div className="text-xs text-secondary">
                                    {asPercent ? absoluteFormatter(slice.value) : `${percent}%`}
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    ) : null

    return (
        <div
            className={clsx(className, 'rounded bg-surface-primary flex flex-1 p-4 gap-4', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
        >
            {!showLegend ? (
                <div className="flex flex-1 min-h-0">
                    <div className="flex flex-1 flex-col min-h-0">
                        <div className="flex flex-col flex-1 min-h-[18rem]">{chart}</div>
                        {totalDisplay}
                    </div>
                </div>
            ) : (
                <>
                    <div className="flex flex-col gap-4 w-full xl:hidden">
                        <div className="flex flex-col">
                            <div className="flex flex-col h-[18rem]">{chart}</div>
                            {totalDisplay}
                        </div>
                        {legend}
                    </div>
                    <div className="hidden xl:flex flex-1 gap-4 min-h-0">
                        <div className="flex flex-1 flex-col min-h-0">
                            <div className="flex flex-col flex-1 min-h-[18rem]">{chart}</div>
                            {totalDisplay}
                        </div>
                        {legend}
                    </div>
                </>
            )}
        </div>
    )
}
