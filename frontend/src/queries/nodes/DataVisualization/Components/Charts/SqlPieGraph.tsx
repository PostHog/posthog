import clsx from 'clsx'
import { useCallback, useMemo } from 'react'

import { ChartLegend, PieChart, TooltipSurface, TooltipSwatch, useChartLegend } from '@posthog/quill-charts'
import type { PieChartConfig, TooltipContext } from '@posthog/quill-charts'

import { ChartDisplayType } from '~/types'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'
import { DonutCenterLabel } from 'products/product_analytics/frontend/insights/trends/TrendsPieChart/DonutCenterLabel'

import { SqlChartProps } from './SqlChart'
import { formatPieSliceCount } from './sqlPieGraphAdapter'
import { useSqlPartOfWholeChart } from './useSqlPartOfWholeChart'

const handleChartError = makeChartErrorHandler('sql-pie-chart')

/**
 * SQL pie graph on @posthog/quill-charts' {@link PieChart}. The chart core and the legend are
 * quill's; the aggregation total stays here as chrome. The legend is driven from here rather than
 * through `config.legend` so a pie total sits in the layout's chart slot, centered under the pie
 * instead of under the pie-plus-legend pair.
 */
export const SqlPieGraph = ({
    xData,
    yData,
    visualizationType,
    chartSettings,
    presetChartHeight,
    className,
}: SqlChartProps): JSX.Element => {
    const isDonut = visualizationType === ChartDisplayType.ActionsDonut
    const { theme, series, legendConfig, total, showTotal, formattingSettings, valueFormatter } =
        useSqlPartOfWholeChart({ xData, yData, chartSettings }, false)

    // Unset means an existing chart from before the labels option — keep showing values. New pies
    // are stamped with 'labels' when the type is picked (see dataVisualizationLogic).
    const sliceContent = chartSettings.pie?.sliceContent ?? 'values'
    const asPercent = (chartSettings.pie?.valueDisplay ?? 'absolute') === 'percentage'

    const { visibleSeries, legendProps } = useChartLegend(series, theme, legendConfig)

    // `isPercent` makes the chart render on-slice values and tooltips as a share of the total; the
    // total keeps using the raw value formatter.
    // Labels sit toward the rim (on the wider part of each wedge) and skip slices under 10% so a
    // long tail of thin slices doesn't pile labels up at the center.
    const pieConfig: PieChartConfig = useMemo(
        () => ({
            showLabelOnSlice: sliceContent === 'labels',
            showValueOnSlice: sliceContent === 'values',
            isPercent: asPercent,
            labelRadiusRatio: 0.72,
            minSlicePercentForLabel: 0.1,
            innerRadiusRatio: isDonut ? 0.6 : undefined,
        }),
        [sliceContent, asPercent, isDonut]
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

    if (!series.length) {
        return (
            <div className={clsx(className, 'rounded bg-surface-primary flex flex-1 items-center justify-center p-6')}>
                <span className="text-secondary text-sm">Pie charts require at least one positive value.</span>
            </div>
        )
    }

    const centerLabel = isDonut && showTotal ? <DonutCenterLabel>{valueFormatter(total)}</DonutCenterLabel> : undefined

    const totalDisplay =
        !isDonut && showTotal ? (
            <div className="pt-4 text-center shrink-0">
                <div className="text-5xl font-bold">{valueFormatter(total)}</div>
            </div>
        ) : null

    // For pies, a side legend narrows the chart column, so the total belongs inside it to stay
    // centered under the pie. A top/bottom legend leaves the column full-width, and the total goes below both.
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
                    runs over the legend and the pie total below it. */}
                <div className="flex flex-col flex-1 min-h-0">
                    <PieChart
                        series={visibleSeries}
                        theme={theme}
                        config={pieConfig}
                        tooltip={renderTooltip}
                        valueFormatter={valueFormatter}
                        centerLabel={centerLabel}
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
