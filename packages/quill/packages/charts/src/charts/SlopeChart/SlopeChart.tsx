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
import { FONT_FAMILY, measureLabelWidth } from '../../utils/text-measure'
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

        const left = startWidth > 0 ? startWidth + VALUE_GAP + EDGE_PAD : EDGE_PAD
        const endGutter = endWidth > 0 ? VALUE_GAP + endWidth : 0
        const nameGutter = nameWidth > 0 ? NAME_GAP + nameWidth : 0
        const right = endGutter || nameGutter ? endGutter + nameGutter + EDGE_PAD : EDGE_PAD

        // Names start just past the end value column.
        const offset = (endWidth > 0 ? VALUE_GAP + endWidth : 0) + NAME_GAP

        const base: Partial<ChartMargins> = { left, right }
        return { margins: { ...base, ...config?.margins }, nameOffsetX: offset }
    }, [series, showsStart, showsEnd, showSeriesLabels, valueFormatter, config?.margins])

    // A slope is a two-point line — collapse each series to its endpoints, with a dot at each.
    const slopeSeries = useMemo<Series<Meta>[]>(
        () =>
            series.map((s) => ({
                ...s,
                data: [slopeStart(s), slopeEnd(s)],
                points: { ...s.points, radius: endpointRadius },
            })),
        [series, endpointRadius]
    )

    const lineConfig = useMemo<LineChartConfig>(
        () => ({ ...config, hideYAxis: config?.hideYAxis ?? true, showGrid: false, margins, valueDomain }),
        [config, margins, valueDomain]
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
                labels={labels}
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
