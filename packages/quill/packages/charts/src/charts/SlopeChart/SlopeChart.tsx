import React, { useCallback, useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { drawAxes } from '../../core/canvas-renderer'
import type { DrawContext } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { createScales as createSlopeScales, yTickCountForHeight } from '../../core/scales'
import type { ScaleSet } from '../../core/scales'
import type {
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    PointClickData,
    ResolvedSeries,
    Series,
    TooltipContext,
    ValueDomain,
} from '../../core/types'
import { FONT_FAMILY, measureLabelWidth } from '../../utils/text-measure'
import { defaultDeltaFormatter, defaultValueFormatter, slopeEnd, slopeStart, type SlopeSeriesMeta } from './slope-data'
import { slopeLegendItems } from './slope-legend'
import { SlopeSeriesLabels } from './SlopeSeriesLabels'
import { SlopeValueLabels } from './SlopeValueLabels'

export type { SlopeSeriesMeta } from './slope-data'

// Brand for the private ChartScales._private slot used by SlopeChart, mirroring LineChart.
interface SlopeChartPrivate {
    __slopeChart: ScaleSet
}

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

    // Per-series start/end value labels can be toggled via `meta`; fall back to the chart default.
    const showsStart = useCallback(
        (s: Series<Meta>): boolean => {
            if (s.visibility?.excluded || s.visibility?.valueLabel === false) {
                return false
            }
            return (s.meta as SlopeSeriesMeta | undefined)?.showStartLabel ?? showStartLabels
        },
        [showStartLabels]
    )
    const showsEnd = useCallback(
        (s: Series<Meta>): boolean => {
            if (s.visibility?.excluded || s.visibility?.valueLabel === false) {
                return false
            }
            return (s.meta as SlopeSeriesMeta | undefined)?.showEndLabel ?? showEndLabels
        },
        [showEndLabels]
    )

    // Reserve left/right gutters sized to the actual label content so the absolutely-positioned
    // value/name labels (which live in the margins, beyond the plot edges) aren't clipped.
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

    // Slope charts encode the value through the start/end labels themselves, so the left value
    // axis is hidden by default; the x-axis keeps the two column labels ("Before"/"After").
    const chartConfig = useMemo<ChartConfig>(() => ({ hideYAxis: true, ...config, margins }), [config, margins])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            const d3Scales = createSlopeScales(coloredSeries, scaleLabels, dimensions, { valueDomain })
            const yTickCount = yTickCountForHeight(dimensions.plotHeight)
            const slopePrivate: SlopeChartPrivate = { __slopeChart: d3Scales }
            return {
                x: (label: string) => d3Scales.x(label),
                y: (value: number) => d3Scales.y(value),
                yTicks: () => d3Scales.y.ticks?.(yTickCount) ?? [],
                _private: slopePrivate,
            }
        },
        [valueDomain]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme: drawTheme }: ChartDrawArgs) => {
            const d3Scales = (scales._private as SlopeChartPrivate | undefined)?.__slopeChart
            if (!d3Scales || drawLabels.length < 2) {
                return
            }

            if (config?.showAxisLines) {
                const baseDrawCtx: DrawContext = {
                    ctx,
                    dimensions,
                    xScale: d3Scales.x,
                    yScale: d3Scales.y,
                    labels: drawLabels,
                }
                drawAxes(baseDrawCtx, { axisColor: drawTheme.gridColor })
            }

            const x0 = d3Scales.x(drawLabels[0])
            const x1 = d3Scales.x(drawLabels[drawLabels.length - 1])
            if (x0 == null || x1 == null) {
                return
            }

            ctx.lineWidth = 2
            ctx.lineCap = 'round'
            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
                    continue
                }
                const y0 = d3Scales.y(slopeStart(s))
                const y1 = d3Scales.y(slopeEnd(s))
                if (!isFinite(y0) || !isFinite(y1)) {
                    continue
                }
                ctx.strokeStyle = s.color
                ctx.beginPath()
                ctx.moveTo(x0, y0)
                ctx.lineTo(x1, y1)
                ctx.stroke()

                ctx.fillStyle = s.color
                for (const [x, y] of [
                    [x0, y0],
                    [x1, y1],
                ]) {
                    ctx.beginPath()
                    ctx.arc(x, y, endpointRadius, 0, Math.PI * 2)
                    ctx.fill()
                }
            }
        },
        [config?.showAxisLines, endpointRadius]
    )

    const drawHover = useCallback(
        ({
            ctx,
            scales,
            series: coloredSeries,
            labels: drawLabels,
            hoverIndex,
            theme: drawTheme,
        }: ChartDrawArgs): boolean => {
            if (hoverIndex < 0 || drawLabels.length < 2) {
                return false
            }
            const x = scales.x(drawLabels[hoverIndex])
            if (x == null) {
                return false
            }
            const background = drawTheme.backgroundColor ?? '#ffffff'
            let drewAny = false
            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
                    continue
                }
                const value = hoverIndex === 0 ? slopeStart(s) : slopeEnd(s)
                const y = scales.y(value)
                if (!isFinite(y)) {
                    continue
                }
                // Halo + filled dot, matching the line color.
                ctx.fillStyle = background
                ctx.beginPath()
                ctx.arc(x, y, endpointRadius + 2, 0, Math.PI * 2)
                ctx.fill()
                ctx.fillStyle = s.color
                ctx.beginPath()
                ctx.arc(x, y, endpointRadius, 0, Math.PI * 2)
                ctx.fill()
                drewAny = true
            }
            return drewAny
        },
        [endpointRadius]
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
            <Chart
                series={series}
                labels={labels}
                config={chartConfig}
                theme={theme}
                createScales={createScales}
                drawStatic={drawStatic}
                drawHover={drawHover}
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
            </Chart>
        </ChartLegend>
    )
}
