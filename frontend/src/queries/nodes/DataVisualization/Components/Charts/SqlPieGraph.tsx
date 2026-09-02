import clsx from 'clsx'
import { useCallback, useMemo, useState } from 'react'

import { ChartLegend, PieChart, TooltipSurface, TooltipSwatch, useChartLegend } from '@posthog/quill-charts'
import type { ChartLegendConfig, PieChartConfig, TooltipContext } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { useChartLegendSeriesMenu } from 'lib/components/ChartLegendSeriesMenu/useChartLegendSeriesMenu'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { SqlChartProps } from './SqlChart'
import { formatSqlSeriesValue } from './sqlLineGraphAdapter'
import { buildPieSeries, buildPieSlices, formatPieSliceCount } from './sqlPieGraphAdapter'

const handleChartError = makeChartErrorHandler('sql-pie-chart')

/**
 * SQL pie graph on @posthog/quill-charts' {@link PieChart}. The chart core and the legend are
 * quill's; the aggregation total stays here as chrome. The legend is driven from here rather than
 * through `config.legend` so the total sits in the layout's chart slot, centered under the pie
 * instead of under the pie-plus-legend pair.
 */
export const SqlPieGraph = ({
    xData,
    yData,
    chartSettings,
    presetChartHeight,
    className,
}: SqlChartProps): JSX.Element => {
    const theme = useChartTheme()

    const slices = useMemo(() => buildPieSlices(xData, yData), [xData, yData])
    const formattingSettings = yData[0]?.settings
    const series = useMemo(() => buildPieSeries(slices), [slices])

    // Toggled-off slices aren't persisted (SQL insights have nowhere to save them), but the legend
    // is controlled anyway so the total and the tooltip shares track the slices actually drawn.
    const [hiddenKeys, setHiddenKeys] = useState<string[]>([])
    const total = useMemo(
        () => series.reduce((sum, s) => (hiddenKeys.includes(s.key) ? sum : sum + (s.data[0] ?? 0)), 0),
        [series, hiddenKeys]
    )

    const showLegend = chartSettings.showLegend ?? false
    // Unset means an existing chart from before the labels option — keep showing values. New pies
    // are stamped with 'labels' when the type is picked (see dataVisualizationLogic).
    const sliceContent = chartSettings.pie?.sliceContent ?? 'values'
    // The total is a sum-of-values readout, so default it on only when slices show values.
    // `showPieTotal` is the legacy top-level toggle — honor it for charts saved before `pie`.
    const showPieTotal = chartSettings.pie?.showTotal ?? chartSettings.showPieTotal ?? sliceContent === 'values'
    const asPercent = (chartSettings.pie?.valueDisplay ?? 'absolute') === 'percentage'

    const absoluteFormatter = useCallback(
        (value: number) => formatSqlSeriesValue(value, formattingSettings),
        [formattingSettings]
    )

    const legendRenderItem = useChartLegendSeriesMenu({ surface: 'sql', seriesCount: series.length })

    const legendConfig: ChartLegendConfig = useMemo(
        () => ({
            show: showLegend,
            position: chartSettings.legendPosition ?? 'right',
            interactive: true,
            hiddenKeys,
            onToggleSeries: (key: string) =>
                setHiddenKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key])),
            onSetHiddenSeries: setHiddenKeys,
            renderItem: legendRenderItem,
        }),
        [showLegend, chartSettings.legendPosition, hiddenKeys, legendRenderItem]
    )

    const { visibleSeries, legendProps } = useChartLegend(series, theme, legendConfig)

    // `isPercent` makes the chart render on-slice values and tooltips as a share of the total; the
    // total below the chart keeps using the raw value formatter.
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

    const totalDisplay = showPieTotal ? (
        <div className="pt-4 text-center shrink-0">
            <div className="text-5xl font-bold">{absoluteFormatter(total)}</div>
        </div>
    ) : null

    // A side legend narrows the chart column, so the total belongs inside it to stay centered under
    // the pie. A top/bottom legend leaves the column full-width, and the total goes below both.
    const legendAtSide = legendProps.show && (legendProps.position === 'left' || legendProps.position === 'right')

    return (
        <div
            className={clsx(className, 'rounded bg-surface-primary flex flex-col flex-1 min-h-0 p-4', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
        >
            <ChartLegend {...legendProps} legendDataAttr="hog-chart-pie-legend">
                {/* min-h-0, not a fixed floor: in a short panel the pie has to shrink, or its box
                    runs over the legend and the total below it. */}
                <div className="flex flex-col flex-1 min-h-0">
                    <PieChart
                        series={visibleSeries}
                        theme={theme}
                        config={pieConfig}
                        tooltip={renderTooltip}
                        valueFormatter={absoluteFormatter}
                        dataAttr="sql-pie-chart"
                        onError={handleChartError}
                    />
                </div>
                {legendAtSide && totalDisplay}
            </ChartLegend>
            {!legendAtSide && totalDisplay}
        </div>
    )
}
