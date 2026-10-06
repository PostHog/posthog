import React, { useCallback, useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { RadialSlicePayload } from '../../core/hooks/useRadialInteraction'
import type {
    BarChartConfig,
    ChartLegendConfig,
    ChartTheme,
    PointClickData,
    Series,
    TooltipContext,
} from '../../core/types'
import { BarChart } from '../BarChart/BarChart'
import { PieTooltip } from '../PieChart/PieTooltip'
import { partValue, proportionLegendItems } from './proportion-bar-data'

export interface ProportionBarConfig {
    /** Bar thickness in px. Default 24. */
    barHeight?: number
    /** Corner radius in px for both ends of the bar. Default 6. */
    barCornerRadius?: number
    /** Legend with one row per part and `share · value` on each row. Unlike the other charts it
     *  shows by default, at the bottom and start-aligned, because the bar has no axis to read a
     *  size from. Same click model as the other charts. */
    legend?: ChartLegendConfig
    tooltip?: {
        enabled?: boolean
    }
}

/** Props match `PieChart` where the two charts overlap, so a consumer can swap one for the other. */
export interface ProportionBarProps<Meta = unknown> {
    /** One series per part, valued like a `PieChart` slice: the sum of `data`, floored at 0. */
    series: Series<Meta>[]
    theme: ChartTheme
    config?: ProportionBarConfig
    /** Formats a part's raw value in the legend and the default tooltip. */
    valueFormatter?: (value: number) => string
    /** Replaces the default tooltip. As on `PieChart`, `ctx.seriesData[0]` is the hovered part,
     *  with its raw `value` and its `fraction` of the visible parts. */
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onSliceClick?: (payload: RadialSlicePayload<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const DEFAULT_BAR_HEIGHT = 24
const DEFAULT_CORNER_RADIUS = 6
const BAND_LABELS = ['total']

export function ProportionBar<Meta = unknown>({ onError, ...rest }: ProportionBarProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <ProportionBarInner {...rest} />
        </ChartErrorBoundary>
    )
}

function defaultValueFormatter(value: number): string {
    return value.toLocaleString()
}

function ProportionBarInner<Meta = unknown>({
    series,
    theme,
    config,
    valueFormatter = defaultValueFormatter,
    tooltip,
    onSliceClick,
    className,
    dataAttr,
}: Omit<ProportionBarProps<Meta>, 'onError'>): React.ReactElement {
    const {
        barHeight = DEFAULT_BAR_HEIGHT,
        barCornerRadius = DEFAULT_CORNER_RADIUS,
        legend,
        tooltip: tooltipConfig,
    } = config ?? {}

    const legendConfig = useMemo<ChartLegendConfig>(
        () => ({ show: true, position: 'bottom', align: 'start', ...legend }),
        [legend]
    )
    const { visibleSeries, legendProps } = useChartLegend(series, theme, legendConfig)
    const legendItems = useMemo(
        () => proportionLegendItems(series, theme, valueFormatter, legendProps.hiddenKeys),
        [series, theme, valueFormatter, legendProps.hiddenKeys]
    )
    const colorByKey = useMemo(() => new Map(legendItems.map((item) => [item.key, item.color])), [legendItems])

    const barSeries = useMemo<Series<Meta>[]>(
        () => visibleSeries.map((s) => ({ ...s, data: [partValue(s)] })),
        [visibleSeries]
    )
    const visibleTotal = useMemo(
        () => barSeries.reduce((acc, s) => (s.visibility?.excluded ? acc : acc + s.data[0]), 0),
        [barSeries]
    )
    const fractionOf = useCallback(
        (value: number): number => (visibleTotal > 0 ? value / visibleTotal : 0),
        [visibleTotal]
    )

    // BarChart layers the library's default axes, grid and margins under any config, so opt out of
    // each one to leave only the bar.
    const barConfig = useMemo<BarChartConfig>(
        () => ({
            barLayout: 'percent',
            axisOrientation: 'horizontal',
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            showCrosshair: false,
            margins: { top: 0, right: 0, bottom: 0, left: 0 },
            barCornerRadius,
            bars: { bandPadding: 0, minBandSize: 0, roundStackEnds: true },
            tooltip: { enabled: tooltipConfig?.enabled !== false },
        }),
        [barCornerRadius, tooltipConfig?.enabled]
    )

    // A percent layout hands the tooltip every segment as a 0..1 fraction. Narrow it to the hovered
    // part with its raw value, which is the context a PieChart tooltip receives.
    const renderTooltip = useCallback(
        (ctx: TooltipContext<Meta>): React.ReactNode => {
            const entry = ctx.seriesData.find((d) => d.series.key === ctx.hoveredSeriesKey)
            if (!entry) {
                return null
            }
            const value = partValue(entry.series)
            const partCtx = { ...ctx, seriesData: [{ ...entry, value, fraction: fractionOf(value) }] }
            return tooltip ? tooltip(partCtx) : <PieTooltip ctx={partCtx} valueFormatter={valueFormatter} />
        },
        [tooltip, fractionOf, valueFormatter]
    )

    const handlePointClick = useCallback(
        ({ series: clicked }: PointClickData<Meta>): void => {
            const sliceIndex = series.findIndex((s) => s.key === clicked.key)
            if (!onSliceClick || sliceIndex < 0) {
                return
            }
            const value = partValue(clicked)
            onSliceClick({
                sliceIndex,
                series: { ...series[sliceIndex], color: colorByKey.get(clicked.key) ?? '' },
                value,
                fraction: fractionOf(value),
            })
        },
        [series, onSliceClick, colorByKey, fractionOf]
    )

    return (
        <div className={className}>
            <ChartLegend {...legendProps} items={legendItems} legendDataAttr="hog-chart-proportion-legend">
                {/* eslint-disable-next-line react/forbid-dom-props -- dynamic pixel height from config */}
                <div className="relative flex flex-col" style={{ height: barHeight }}>
                    <BarChart
                        series={barSeries}
                        labels={BAND_LABELS}
                        theme={theme}
                        config={barConfig}
                        tooltip={renderTooltip}
                        onPointClick={onSliceClick ? handlePointClick : undefined}
                        dataAttr={dataAttr}
                    />
                </div>
            </ChartLegend>
        </div>
    )
}
