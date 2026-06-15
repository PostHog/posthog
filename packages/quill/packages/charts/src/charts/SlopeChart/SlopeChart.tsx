import React, { useCallback, useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type {
    ChartConfig,
    ChartMargins,
    ChartTheme,
    LineChartConfig,
    PointClickData,
    Series,
    TooltipContext,
    ValueDomain,
} from '../../core/types'
import { AXIS_LABEL_FONT, FONT_FAMILY, measureLabelWidth } from '../../utils/text-measure'
import { LineChart } from '../LineChart/LineChart'
import {
    defaultDeltaFormatter,
    defaultValueFormatter,
    slopeEnd,
    slopeLabelVisible,
    slopeStart,
    type SlopeSeriesMeta,
} from './slope-data'
import { slopeLegendItems } from './slope-legend'
import { SlopeSeriesLabels } from './SlopeSeriesLabels'
import { SlopeValueLabels } from './SlopeValueLabels'

export type { SlopeSeriesMeta } from './slope-data'

const LABEL_FONT = `600 12px ${FONT_FAMILY}`
const VALUE_GAP = 8
const NAME_GAP = 8
const EDGE_PAD = 8
const DEFAULT_ENDPOINT_RADIUS = 4
// Synthetic, hidden x-axis label for the collinear midpoint inserted when the end is incomplete.
const SLOPE_MIDPOINT_LABEL = '__slope_mid__'

export interface SlopeChartLegendConfig {
    /** Show the legend. Default false. */
    show?: boolean
    position?: 'top' | 'bottom' | 'left' | 'right'
    align?: 'start' | 'center' | 'end'
    gap?: number
}

export interface SlopeChartConfig extends ChartConfig {
    /** Show the series name labels beside each end point. Default true. */
    showSeriesLabels?: boolean
    /** Default for the start (left) value labels; per-series `meta.showStartLabel` overrides. Default true. */
    showStartLabels?: boolean
    /** Default for the end (right) value labels; per-series `meta.showEndLabel` overrides. Default true. */
    showEndLabels?: boolean
    /** Legend visibility + placement. Hidden by default. */
    legend?: SlopeChartLegendConfig
    /** Formats the start/end value labels. Defaults to `toLocaleString`. */
    valueFormatter?: (value: number) => string
    /** Formats the per-series change shown in the legend. Defaults to a signed `toLocaleString`. */
    deltaFormatter?: (delta: number) => string
    /** Radius of the endpoint dots in px. Default 4. */
    endpointRadius?: number
    /** Value-axis domain control — omit for data-derived auto-scaling. */
    valueDomain?: ValueDomain
}

export interface SlopeChartProps<Meta = SlopeSeriesMeta> {
    series: Series<Meta>[]
    labels: string[]
    config?: SlopeChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function SlopeChart<Meta = SlopeSeriesMeta>({ onError, ...rest }: SlopeChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <SlopeChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function maxLabelWidth(texts: string[]): number {
    return texts.reduce((max, t) => Math.max(max, measureLabelWidth(t, LABEL_FONT)), 0)
}

function SlopeChartInner<Meta = SlopeSeriesMeta>({
    series,
    labels,
    config,
    theme,
    tooltip,
    onPointClick,
    className,
    dataAttr,
    children,
}: SlopeChartProps<Meta>): React.ReactElement {
    const {
        showSeriesLabels = true,
        showStartLabels = true,
        showEndLabels = true,
        legend,
        valueFormatter = defaultValueFormatter,
        deltaFormatter = defaultDeltaFormatter,
        endpointRadius = DEFAULT_ENDPOINT_RADIUS,
        valueDomain,
    } = config ?? {}

    const showsStart = useCallback(
        (s: Series<Meta>): boolean => slopeLabelVisible(s, 'start', showStartLabels),
        [showStartLabels]
    )
    const showsEnd = useCallback(
        (s: Series<Meta>): boolean => slopeLabelVisible(s, 'end', showEndLabels),
        [showEndLabels]
    )

    // Reserve left/right gutters for the value/name labels, which sit in the margins beyond the plot.
    const { margins, nameOffsetX } = useMemo(() => {
        const startWidth = maxLabelWidth(series.filter(showsStart).map((s) => valueFormatter(slopeStart(s))))
        const endWidth = maxLabelWidth(series.filter(showsEnd).map((s) => valueFormatter(slopeEnd(s))))
        const nameWidth = showSeriesLabels
            ? maxLabelWidth(
                  series
                      .filter((s) => !s.visibility?.excluded && s.visibility?.valueLabel !== false)
                      .map((s) => s.label)
              )
            : 0

        // The x-axis labels sit centred under the two endpoints, so half of the first/last label
        // overhangs the side gutter — reserve room for it too, else a wide label (e.g. a date) clips.
        const firstAxisHalf = labels.length > 0 ? measureLabelWidth(labels[0], AXIS_LABEL_FONT) / 2 : 0
        const lastAxisHalf = labels.length > 1 ? measureLabelWidth(labels[labels.length - 1], AXIS_LABEL_FONT) / 2 : 0

        const left = Math.max(startWidth > 0 ? startWidth + VALUE_GAP + EDGE_PAD : EDGE_PAD, firstAxisHalf + EDGE_PAD)
        const endGutter = endWidth > 0 ? VALUE_GAP + endWidth : 0
        const nameGutter = nameWidth > 0 ? NAME_GAP + nameWidth : 0
        const right = Math.max(
            endGutter || nameGutter ? endGutter + nameGutter + EDGE_PAD : EDGE_PAD,
            lastAxisHalf + EDGE_PAD
        )

        // Names start just past the end value column.
        const offset = (endWidth > 0 ? VALUE_GAP + endWidth : 0) + NAME_GAP

        const base: Partial<ChartMargins> = { left, right }
        return { margins: { ...base, ...config?.margins }, nameOffsetX: offset }
    }, [series, labels, showsStart, showsEnd, showSeriesLabels, valueFormatter, config?.margins])

    // When the end point is the current incomplete period, dash only the *second half* of the
    // connector so it reads as "the end is provisional", not the whole comparison.
    const dashEnd = useMemo(() => series.some((s) => (s.meta as SlopeSeriesMeta | undefined)?.incompleteEnd), [series])

    // A slope is a two-point line — collapse each series to its endpoints, with a dot at each. For a
    // dashed end we insert a collinear midpoint (no dot) so the connector splits into a solid first
    // half and a dashed second half.
    const slopeSeries = useMemo<Series<Meta>[]>(
        () =>
            series.map((s) => {
                const start = slopeStart(s)
                const end = slopeEnd(s)
                if (dashEnd) {
                    return {
                        ...s,
                        data: [start, (start + end) / 2, end],
                        points: { ...s.points, radius: endpointRadius, startAndEndValuesOnly: true },
                        stroke: { ...s.stroke, partial: { ...s.stroke?.partial, fromIndex: 2 } },
                    }
                }
                return { ...s, data: [start, end], points: { ...s.points, radius: endpointRadius } }
            }),
        [series, endpointRadius, dashEnd]
    )

    // The midpoint needs a label slot to occupy, but it must not render a tick — hide it.
    const axisLabels = useMemo(
        () => (dashEnd && labels.length >= 2 ? [labels[0], SLOPE_MIDPOINT_LABEL, labels[labels.length - 1]] : labels),
        [dashEnd, labels]
    )

    const lineConfig = useMemo<LineChartConfig>(
        () => ({
            ...config,
            hideYAxis: config?.hideYAxis ?? true,
            showGrid: false,
            margins,
            valueDomain,
            xTickFormatter: dashEnd
                ? (value: string, index: number): string | null =>
                      value === SLOPE_MIDPOINT_LABEL ? null : (config?.xTickFormatter?.(value, index) ?? value)
                : config?.xTickFormatter,
        }),
        [config, margins, valueDomain, dashEnd]
    )

    const legendItems = useMemo(() => slopeLegendItems(series, theme, deltaFormatter), [series, theme, deltaFormatter])

    return (
        <ChartLegend
            show={legend?.show ?? false}
            items={legendItems}
            position={legend?.position ?? 'bottom'}
            align={legend?.align}
            gap={legend?.gap}
            legendDataAttr="hog-chart-slope-legend"
        >
            <LineChart<Meta>
                series={slopeSeries}
                labels={axisLabels}
                config={lineConfig}
                theme={theme}
                tooltip={tooltip}
                onPointClick={onPointClick}
                className={className}
                dataAttr={dataAttr}
            >
                <SlopeValueLabels
                    valueFormatter={valueFormatter}
                    showStartLabels={showStartLabels}
                    showEndLabels={showEndLabels}
                />
                <SlopeSeriesLabels show={showSeriesLabels} offsetX={nameOffsetX} />
                {children}
            </LineChart>
        </ChartLegend>
    )
}
