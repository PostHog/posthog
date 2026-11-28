import React, { useCallback, useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import { seriesKeysAtCursor } from '../../core/band-slot'
import { drawAxes, drawGrid, resolveAxisLineColor, type DrawContext } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { applyChartDefaults } from '../../core/chart-config'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { dimColor } from '../../core/color-utils'
import { createBarScales, type BarScaleSet, yTickCountForHeight } from '../../core/scales'
import { useResolvedChartTheme } from '../../core/theme'
import { resolveAxisLines } from '../../core/types'
import type {
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartLegendConfig,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    ResolvedSeries,
    Series,
    TooltipContext,
} from '../../core/types'
import { computeSeriesViolins, summarizeViolin } from './computeViolinLayout'
import { drawViolinHighlight, drawViolins } from './draw-violins'
import type { ViolinPlotDatum, ViolinPlotSeries, ViolinRect } from './types'
import { ViolinPlotTooltip } from './ViolinPlotTooltip'

/** Stash slot — survives a render via `ChartScales._private` so drawStatic/drawHover can read the
 *  d3 scales and the per-series datums lookup without recomputing them. */
interface ViolinPlotPrivate {
    __violinPlot: {
        scales: BarScaleSet
        violinsByKey: Map<string, (ViolinRect | null)[]>
        grouped: boolean
    }
}

/** Meta attached to the inner adapter `Series` handed to the `Chart` base — carries the original
 *  observations indexed by x-position, plus any user-supplied meta. */
export interface ViolinPlotAdaptedMeta<Meta = unknown> {
    datums: (ViolinPlotDatum | null)[]
    user?: Meta
}

/** Tooltip context handed to consumer-supplied `tooltip` callbacks. Same shape as
 *  `TooltipContext` with the `ViolinPlotAdaptedMeta` `Meta` parameter baked in. */
export type ViolinPlotTooltipContext<Meta = unknown> = TooltipContext<ViolinPlotAdaptedMeta<Meta>>

/** Chart-level config. The violins stand upright: the value axis is always vertical, so
 *  `axisOrientation` is not accepted. */
export interface ViolinPlotConfig extends Omit<ChartConfig, 'axisOrientation'> {
    legend?: Omit<ChartLegendConfig, 'table'>
    /** Draw one marker per observation over each violin. Defaults to true. */
    showPoints?: boolean
}

export interface ViolinPlotProps<Meta = unknown> {
    series: ViolinPlotSeries<Meta>[]
    labels: string[]
    /** Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars. */
    theme?: ChartTheme
    config?: ViolinPlotConfig
    /** Optional custom tooltip. Receives the adapter `TooltipContext`; consumers can read
     *  the original datum back out via `entry.series.meta?.datums?.[ctx.dataIndex]`. */
    tooltip?: (ctx: ViolinPlotTooltipContext<Meta>) => React.ReactNode
    className?: string
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

/** Places each laid-out violin at its x position so the hover path can look one up by index. */
function violinsByDataIndex(violins: ViolinRect[], length: number): (ViolinRect | null)[] {
    const out: (ViolinRect | null)[] = Array.from({ length }, () => null)
    for (const violin of violins) {
        out[violin.dataIndex] = violin
    }
    return out
}

export function ViolinPlot<Meta = unknown>({ onError, ...rest }: ViolinPlotProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError} resetKey={rest.series}>
            <ViolinPlotInner {...rest} />
        </ChartErrorBoundary>
    )
}

function ViolinPlotInner<Meta = unknown>({
    series,
    labels,
    theme: themeProp,
    config: rawConfig,
    tooltip,
    className,
    dataAttr,
    children,
}: Omit<ViolinPlotProps<Meta>, 'onError'>): React.ReactElement {
    const theme = useResolvedChartTheme(themeProp)
    const config = useMemo(() => applyChartDefaults(rawConfig), [rawConfig])
    const { yScaleType = 'linear', showGrid, showAxisLines, showPoints = true } = config ?? {}
    const logScale = yScaleType === 'log'
    const { x: xAxisLine, y: yAxisLine } = resolveAxisLines(showAxisLines)

    const adaptedSeries = useMemo<Series<ViolinPlotAdaptedMeta<Meta>>[]>(
        () =>
            series.map((s) => ({
                key: s.key,
                label: s.label,
                color: s.color,
                data: Array.from({ length: labels.length }, (_, i) => {
                    const datum = s.data[i]
                    return (datum ? summarizeViolin(datum, logScale)?.median : undefined) ?? Number.NaN
                }),
                meta: { datums: s.data, user: s.meta },
                visibility: s.visibility,
            })),
        [series, labels.length, logScale]
    )

    const { visibleSeries, legendProps } = useChartLegend(adaptedSeries, theme, config?.legend)
    const grouped = visibleSeries.filter((s) => !s.visibility?.excluded).length > 1

    /** Synthetic series carrying the lowest and highest observation per violin so the y-domain spans
     *  every value, not just the medians. Fed to `createBarScales` (as `stackedSeries`) for the d3
     *  scale and to `Chart` (as `valueRangeSeries`) for tick sizing, so hidden series cannot affect
     *  either calculation. */
    const valueRangeSeries = useMemo<Series[]>(() => {
        const out: Series[] = []
        for (const s of visibleSeries) {
            if (s.visibility?.excluded) {
                continue
            }
            const mins: number[] = []
            const maxs: number[] = []
            for (const datum of s.meta?.datums ?? []) {
                const summary = datum ? summarizeViolin(datum, logScale) : null
                if (summary) {
                    mins.push(summary.min)
                    maxs.push(summary.max)
                }
            }
            if (mins.length > 0) {
                out.push({ key: `${s.key}__min`, label: s.label, data: mins })
                out.push({ key: `${s.key}__max`, label: s.label, data: maxs })
            }
        }
        return out
    }, [visibleSeries, logScale])

    const datumsByKey = useMemo(() => new Map(series.map((s) => [s.key, s.data])), [series])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            const d3Scales = createBarScales(coloredSeries, scaleLabels, dimensions, {
                scaleType: yScaleType,
                barLayout: grouped ? 'grouped' : 'stacked',
                axisOrientation: 'vertical',
                stackedSeries: valueRangeSeries.length > 0 ? valueRangeSeries : undefined,
            })

            const yTickCount = yTickCountForHeight(dimensions.plotHeight)
            const violinsByKey = new Map<string, (ViolinRect | null)[]>()
            for (const s of coloredSeries) {
                const datums = datumsByKey.get(s.key)
                if (s.visibility?.excluded || !datums) {
                    continue
                }
                violinsByKey.set(
                    s.key,
                    violinsByDataIndex(
                        computeSeriesViolins({
                            seriesKey: s.key,
                            data: datums,
                            labels: scaleLabels,
                            scales: d3Scales,
                            grouped,
                            logScale,
                            showPoints,
                        }),
                        scaleLabels.length
                    )
                )
            }
            const priv: ViolinPlotPrivate = {
                __violinPlot: { scales: d3Scales, violinsByKey, grouped },
            }

            return {
                x: (label: string, seriesKey?: string) => {
                    const start = d3Scales.band(label)
                    if (start == null) {
                        return undefined
                    }
                    if (grouped && seriesKey != null) {
                        const groupOffset = d3Scales.group?.(seriesKey)
                        const groupBandwidth = d3Scales.group?.bandwidth()
                        if (groupOffset != null && groupBandwidth != null) {
                            return start + groupOffset + groupBandwidth / 2
                        }
                    }
                    return start + d3Scales.band.bandwidth() / 2
                },
                y: (value: number) => d3Scales.value(value),
                yTicks: () => d3Scales.value.ticks?.(yTickCount) ?? [],
                _private: priv,
            }
        },
        [grouped, yScaleType, valueRangeSeries, datumsByKey, logScale, showPoints]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme }: ChartDrawArgs) => {
            const priv = (scales._private as ViolinPlotPrivate | undefined)?.__violinPlot
            if (!priv) {
                return
            }

            const baseDrawCtx: DrawContext = {
                ctx,
                dimensions,
                xScale: (label: string) => {
                    const start = priv.scales.band(label)
                    return start == null ? undefined : start + priv.scales.band.bandwidth() / 2
                },
                yScale: priv.scales.value,
                labels: drawLabels,
            }

            const axisLineStyle = xAxisLine || yAxisLine
            if (showGrid) {
                drawGrid(baseDrawCtx, {
                    gridColor: theme.gridColor,
                    gridDash: theme.gridDashPattern,
                    frame: !axisLineStyle,
                })
            }

            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
                    continue
                }
                const violins = priv.violinsByKey.get(s.key)?.filter((violin): violin is ViolinRect => violin != null)
                if (!violins) {
                    continue
                }
                drawViolins(ctx, violins, {
                    color: s.color,
                    fillColor: dimColor(s.color, 0.35),
                    medianColor: theme.axisColor ?? s.color,
                    pointFillColor: s.color,
                    pointStrokeColor: theme.backgroundColor ?? dimColor(s.color, 0.5),
                    meanFillColor: theme.backgroundColor ?? dimColor(s.color, 0.5),
                })
            }

            if (axisLineStyle) {
                drawAxes(baseDrawCtx, {
                    axisColor: resolveAxisLineColor(theme),
                    xLine: xAxisLine,
                    yLine: yAxisLine,
                })
            }
        },
        [showGrid, xAxisLine, yAxisLine]
    )

    const drawHover = useCallback(
        ({
            ctx,
            scales,
            series: coloredSeries,
            labels: drawLabels,
            hoverIndex,
            hoverPosition,
        }: ChartDrawArgs): boolean => {
            const priv = (scales._private as ViolinPlotPrivate | undefined)?.__violinPlot
            if (!priv || hoverIndex < 0 || !hoverPosition) {
                return false
            }
            const hoveredLabel = drawLabels[hoverIndex]
            const hits = seriesKeysAtCursor({
                series,
                label: hoveredLabel,
                dataIndex: hoverIndex,
                cursor: hoverPosition,
                scales: priv.scales,
                grouped: priv.grouped,
            })
            let drewAny = false
            for (const s of coloredSeries) {
                const violin = priv.violinsByKey.get(s.key)?.[hoverIndex]
                if (s.visibility?.excluded || !hits.has(s.key)) {
                    continue
                }
                if (violin) {
                    drawViolinHighlight(ctx, violin, dimColor(s.color, 0.25))
                    drewAny = true
                }
            }
            return drewAny
        },
        [series]
    )

    const renderTooltip = (ctx: TooltipContext<ViolinPlotAdaptedMeta<Meta>>): React.ReactNode => (
        <ViolinPlotTooltip<Meta>
            ctx={ctx}
            userTooltip={tooltip}
            logScale={logScale}
            grouped={grouped}
            valueFormatter={config?.tooltip?.valueFormatter}
        />
    )

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-violin-plot-legend">
            <Chart<ViolinPlotAdaptedMeta<Meta>>
                series={visibleSeries}
                labels={labels}
                config={{ ...config, axisOrientation: 'vertical' }}
                theme={theme}
                createScales={createScales}
                drawStatic={drawStatic}
                drawHover={drawHover}
                tooltip={renderTooltip}
                valueRangeSeries={valueRangeSeries.length > 0 ? valueRangeSeries : undefined}
                className={className}
                dataAttr={dataAttr}
            >
                {children}
            </Chart>
        </ChartLegend>
    )
}
