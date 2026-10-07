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

/** Shares `series`, `valueFormatter`, `tooltip`, `onSliceClick` and `config.legend` with `PieChart`.
 *  It has no `isPercent`, `sliceValueDisplay` or `config.sliceValue`: the bar always shows each
 *  part's share and value, and always values a part as the sum of its data. */
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
            <ProportionBarInner {...rest} onError={onError} />
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
    onError,
}: ProportionBarProps<Meta>): React.ReactElement {
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
    // Tooltips and clicks hand back the consumer's own series, not the single-value copies the bar draws.
    const seriesByKey = useMemo(() => new Map(series.map((s) => [s.key, s])), [series])

    // Only the fields the bar needs to draw and identify a part. Carrying the rest of `s` through
    // (yAxisId, overlay, fill.lowerData, per-bar `bars` overrides) would let it change how the part
    // is drawn or stacked, which `PieChart` has no equivalent for.
    const barSeries = useMemo<Series<Meta>[]>(
        () =>
            visibleSeries.map((s) => ({
                key: s.key,
                label: s.label,
                color: s.color,
                visibility: s.visibility,
                meta: s.meta,
                data: [partValue(s)],
            })),
        [visibleSeries]
    )
    const valueByKey = useMemo(() => new Map(barSeries.map((s) => [s.key, s.data[0]])), [barSeries])
    const visibleTotal = useMemo(
        () => barSeries.reduce((acc, s) => (s.visibility?.excluded ? acc : acc + s.data[0]), 0),
        [barSeries]
    )
    // As on PieChart, a slice index counts only the drawn parts, so a hidden part does not shift it.
    const drawnKeys = useMemo(() => barSeries.filter((s) => !s.visibility?.excluded).map((s) => s.key), [barSeries])
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
    // part with its raw value, which is the context a PieChart tooltip receives. Reads the value
    // already computed for `barSeries` instead of rescanning the part's data on every hover.
    const renderTooltip = useCallback(
        (ctx: TooltipContext<Meta>): React.ReactNode => {
            const entry = ctx.seriesData.find((d) => d.series.key === ctx.hoveredSeriesKey)
            if (!entry) {
                return null
            }
            const original = seriesByKey.get(entry.series.key) ?? entry.series
            const part = { ...original, color: colorByKey.get(original.key) ?? entry.color }
            const value = valueByKey.get(entry.series.key) ?? 0
            const partCtx = {
                ...ctx,
                label: part.label,
                dataIndex: series.indexOf(original),
                seriesData: [{ ...entry, series: part, value, fraction: fractionOf(value) }],
            }
            return tooltip ? tooltip(partCtx) : <PieTooltip ctx={partCtx} valueFormatter={valueFormatter} />
        },
        [tooltip, series, seriesByKey, colorByKey, valueByKey, fractionOf, valueFormatter]
    )

    const handlePointClick = useCallback(
        ({ series: clicked }: PointClickData<Meta>): void => {
            const part = seriesByKey.get(clicked.key)
            const sliceIndex = drawnKeys.indexOf(clicked.key)
            const value = valueByKey.get(clicked.key) ?? 0
            // A part with no visible width (value 0, or the whole bar empty) draws nothing. `PieChart`
            // draws no slice and fires no click for it, so match that here.
            if (!onSliceClick || !part || sliceIndex < 0 || visibleTotal <= 0 || value <= 0) {
                return
            }
            onSliceClick({
                sliceIndex,
                series: { ...part, color: colorByKey.get(part.key) ?? '' },
                value,
                fraction: fractionOf(value),
            })
        },
        [seriesByKey, drawnKeys, valueByKey, visibleTotal, onSliceClick, colorByKey, fractionOf]
    )

    return (
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
                    className={className}
                    dataAttr={dataAttr}
                    onError={onError}
                />
            </div>
        </ChartLegend>
    )
}
