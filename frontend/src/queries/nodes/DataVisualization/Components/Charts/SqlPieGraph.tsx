import clsx from 'clsx'
import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { LemonColorGlyph } from '@posthog/lemon-ui'
import { PieChart, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { PieChartConfig, TooltipContext } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

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
    const { isDarkModeOn } = useValues(themeLogic)
    // isDarkModeOn invalidates the memo so buildTheme() re-reads CSS vars on dark-mode toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

    const slices = useMemo(() => buildPieSlices(xData, yData), [xData, yData])
    const formattingSettings = yData[0]?.settings
    const series = useMemo(() => buildPieSeries(slices), [slices])
    const total = useMemo(() => slices.reduce((sum, slice) => sum + slice.value, 0), [slices])

    const showLegend = chartSettings.showLegend ?? false
    const showPieTotal = chartSettings.showPieTotal ?? true

    const valueFormatter = useCallback(
        (value: number) => String(formatDataWithSettings(value, formattingSettings) ?? value),
        [formattingSettings]
    )

    const pieConfig: PieChartConfig = useMemo(
        () => ({ showValueOnSlice: chartSettings.showValuesOnSeries ?? true }),
        [chartSettings.showValuesOnSeries]
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
                            {formatPieSliceCount(entry.value, total, formattingSettings)}
                        </strong>
                    </div>
                </TooltipSurface>
            )
        },
        [total, formattingSettings]
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
            valueFormatter={valueFormatter}
            dataAttr="sql-pie-chart"
            onError={handleChartError}
        />
    )

    const totalDisplay = showPieTotal ? (
        <div className="pt-4 text-center shrink-0">
            <div className="text-5xl font-bold">{valueFormatter(total)}</div>
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
                                <div className="font-semibold">{valueFormatter(slice.value)}</div>
                                <div className="text-xs text-secondary">{percent}%</div>
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
