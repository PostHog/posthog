import React, { useCallback, useMemo } from 'react'

import { drawBox, drawBoxHighlight, drawGrid, type DrawContext } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { createBarScales, type BarScaleSet, yTickCountForHeight } from '../../core/scales'
import type {
    ChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    PointClickData,
    ResolvedSeries,
    Series,
    TooltipContext,
} from '../../core/types'
import { BoxPlotTooltip } from './BoxPlotTooltip'
import {
    computeBoxRect,
    computeSeriesBoxes,
    type BoxPlotDatum,
    type BoxPlotSeries,
    type BoxRect,
} from './computeBoxLayout'
import { seriesKeysAtCursor } from './utils/boxes-under-cursor'

/** Stash slot — survives a render via `ChartScales._private` so drawStatic/drawHover
 *  can read the d3 scales and the per-series datums lookup without recomputing them. */
interface BoxPlotPrivate {
    __boxPlot: {
        scales: BarScaleSet
        datumsByKey: Map<string, (BoxPlotDatum | null)[]>
        grouped: boolean
    }
}

/** Meta we attach to the inner `Series` we hand to the Chart base — carries the original
 *  six-number summary for each x-index plus any user-supplied meta. */
interface BoxPlotAdaptedMeta<Meta> {
    datums: (BoxPlotDatum | null)[]
    user?: Meta
}

export interface BoxPlotConfig extends ChartConfig {
    /** Mean marker radius in CSS pixels. Defaults to 3. */
    meanRadius?: number
    /** Whisker cap width as a fraction of the box width. Defaults to 0.6. */
    whiskerCapRatio?: number
    /** Box outline / whisker stroke width. Defaults to 1.5. */
    boxStrokeWidth?: number
}

export interface BoxPlotClickData<Meta = unknown> {
    /** Series at the clicked column (the original `BoxPlotSeries`, not the inner Series adapter). */
    series: BoxPlotSeries<Meta>
    /** Index of the box's series in the input `series` array. */
    seriesIndex: number
    /** Index along the x-axis (into `labels`). */
    dataIndex: number
    /** The x-axis label at this index. */
    label: string
    /** The six-number summary that was clicked. */
    datum: BoxPlotDatum
    /** All visible boxes at this column, for cross-series comparisons. */
    crossSeriesData: { series: BoxPlotSeries<Meta>; datum: BoxPlotDatum }[]
}

export interface BoxPlotProps<Meta = unknown> {
    series: BoxPlotSeries<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: BoxPlotConfig
    /** Optional custom tooltip. Receives the inner adapter's `TooltipContext`; consumers can
     *  pull the original datum back out via `entry.series.meta.datums[ctx.dataIndex]`. */
    tooltip?: (ctx: TooltipContext<BoxPlotAdaptedMeta<Meta>>) => React.ReactNode
    /** Click callback — fired when the user clicks a box. The product layer wires this to
     *  the persons modal in the BoxPlot insight. */
    onBoxClick?: (data: BoxPlotClickData<Meta>) => void
    className?: string
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function BoxPlot<Meta = unknown>({ onError, ...rest }: BoxPlotProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <BoxPlotInner {...rest} />
        </ChartErrorBoundary>
    )
}

function BoxPlotInner<Meta = unknown>({
    series,
    labels,
    theme,
    config,
    tooltip,
    onBoxClick,
    className,
    dataAttr,
    children,
}: Omit<BoxPlotProps<Meta>, 'onError'>): React.ReactElement {
    const {
        yScaleType = 'linear',
        showGrid = false,
        xTickFormatter,
        meanRadius = 3,
        whiskerCapRatio = 0.6,
        boxStrokeWidth = 1.5,
    } = config ?? {}

    const grouped = useMemo(() => series.filter((s) => !s.visibility?.excluded).length > 1, [series])

    /** The inner Series.data is medians at indices `[0, labels.length)` (matches interaction's
     *  per-label addressing, and lets the default `resolveValue` return the median for the
     *  tooltip). Per-series whisker min/max are appended past `labels.length` so
     *  `useChartMargins` — which sizes the y-tick column from `seriesValueRange(series)` —
     *  sees the real value extent and doesn't undersize the left margin when whiskers are
     *  much larger than medians. Extra entries are never indexed (interaction reads
     *  `labels.length`, draw reads `meta.datums`). */
    const adaptedSeries = useMemo<Series<BoxPlotAdaptedMeta<Meta>>[]>(
        () =>
            series.map((s) => {
                const medians: number[] = Array.from({ length: labels.length }, (_, i) => {
                    const datum = s.data[i]
                    return datum && isFinite(datum.median) ? datum.median : Number.NaN
                })
                let seriesMin = Infinity
                let seriesMax = -Infinity
                for (const datum of s.data) {
                    if (!datum) {
                        continue
                    }
                    if (isFinite(datum.min) && datum.min < seriesMin) {
                        seriesMin = datum.min
                    }
                    if (isFinite(datum.max) && datum.max > seriesMax) {
                        seriesMax = datum.max
                    }
                }
                const data = medians.slice()
                if (isFinite(seriesMin)) {
                    data.push(seriesMin)
                }
                if (isFinite(seriesMax)) {
                    data.push(seriesMax)
                }
                return {
                    key: s.key,
                    label: s.label,
                    color: s.color,
                    data,
                    meta: { datums: s.data, user: s.meta },
                    visibility: s.visibility,
                }
            }),
        [series, labels.length]
    )

    /** Synthetic series carrying min/max samples so `seriesValueRange` (inside createBarScales)
     *  produces a y-domain that spans every whisker — not just the medians on `data`. */
    const valueRangeSeries = useMemo<Series[]>(() => {
        const out: Series[] = []
        for (const s of series) {
            if (s.visibility?.excluded) {
                continue
            }
            const mins: number[] = []
            const maxs: number[] = []
            for (const datum of s.data) {
                if (!datum) {
                    continue
                }
                if (isFinite(datum.min)) {
                    mins.push(datum.min)
                }
                if (isFinite(datum.max)) {
                    maxs.push(datum.max)
                }
            }
            if (mins.length > 0) {
                out.push({ key: `${s.key}__min`, label: s.label, data: mins })
            }
            if (maxs.length > 0) {
                out.push({ key: `${s.key}__max`, label: s.label, data: maxs })
            }
        }
        return out
    }, [series])

    const datumsByKey = useMemo<Map<string, (BoxPlotDatum | null)[]>>(() => {
        const m = new Map<string, (BoxPlotDatum | null)[]>()
        for (const s of series) {
            m.set(s.key, s.data)
        }
        return m
    }, [series])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            const barLayout = grouped ? 'grouped' : 'stacked'
            const d3Scales = createBarScales(coloredSeries, scaleLabels, dimensions, {
                scaleType: yScaleType,
                barLayout,
                axisOrientation: 'vertical',
                stackedSeries: valueRangeSeries.length > 0 ? valueRangeSeries : undefined,
            })

            const yTickCount = yTickCountForHeight(dimensions.plotHeight)
            const priv: BoxPlotPrivate = {
                __boxPlot: { scales: d3Scales, datumsByKey, grouped },
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
        [grouped, yScaleType, valueRangeSeries, datumsByKey]
    )

    const drawStatic = useCallback(
        ({ ctx, dimensions, scales, series: coloredSeries, labels: drawLabels, theme }: ChartDrawArgs) => {
            const priv = (scales._private as BoxPlotPrivate | undefined)?.__boxPlot
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

            if (showGrid) {
                drawGrid(baseDrawCtx, { gridColor: theme.gridColor, orientation: 'vertical' })
            }

            for (const s of coloredSeries) {
                if (s.visibility?.excluded) {
                    continue
                }
                const datums = priv.datumsByKey.get(s.key)
                if (!datums) {
                    continue
                }
                const boxes = computeSeriesBoxes({
                    seriesKey: s.key,
                    data: datums,
                    labels: drawLabels,
                    scales: priv.scales,
                    grouped: priv.grouped,
                })
                drawSeriesBoxes(ctx, boxes, s.color, {
                    meanRadius,
                    whiskerCapRatio,
                    boxStrokeWidth,
                })
            }
        },
        [showGrid, meanRadius, whiskerCapRatio, boxStrokeWidth]
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
            const priv = (scales._private as BoxPlotPrivate | undefined)?.__boxPlot
            if (!priv || hoverIndex < 0 || !hoverPosition) {
                return false
            }
            const hoveredLabel = drawLabels[hoverIndex]

            // Same band-axis hit-test as BarChart's hover layer — keeps the highlight
            // anchored to whichever group slot the cursor lines up with.
            const hits = seriesKeysAtCursor<unknown>({
                series: coloredSeries.map((s) => ({
                    key: s.key,
                    label: s.label,
                    color: s.color,
                    data: priv.datumsByKey.get(s.key) ?? [],
                    visibility: s.visibility,
                })),
                label: hoveredLabel,
                dataIndex: hoverIndex,
                cursor: hoverPosition,
                scales: priv.scales,
                grouped: priv.grouped,
            })
            if (hits.size === 0) {
                return false
            }
            let drewAny = false
            for (const s of coloredSeries) {
                if (s.visibility?.excluded || !hits.has(s.key)) {
                    continue
                }
                const datums = priv.datumsByKey.get(s.key)
                const datum = datums?.[hoverIndex]
                if (!datum) {
                    continue
                }
                const box = computeBoxRect({
                    seriesKey: s.key,
                    label: hoveredLabel,
                    dataIndex: hoverIndex,
                    datum,
                    scales: priv.scales,
                    grouped: priv.grouped,
                })
                if (!box) {
                    continue
                }
                drawBoxHighlight(ctx, box, hexToRgba(s.color, 0.25))
                drewAny = true
            }
            return drewAny
        },
        []
    )

    const renderTooltip = useCallback(
        (ctx: TooltipContext<BoxPlotAdaptedMeta<Meta>>) => (
            <BoxPlotTooltip<Meta> ctx={ctx} userTooltip={tooltip} grouped={grouped} />
        ),
        [tooltip, grouped]
    )

    const onPointClick = useCallback(
        (data: PointClickData<BoxPlotAdaptedMeta<Meta>>): void => {
            if (!onBoxClick) {
                return
            }
            const primaryDatums = data.series.meta?.datums
            const datum = primaryDatums?.[data.dataIndex]
            if (!datum) {
                return
            }
            const crossSeriesData: BoxPlotClickData<Meta>['crossSeriesData'] = []
            for (const entry of data.crossSeriesData) {
                const ds = entry.series.meta?.datums?.[data.dataIndex]
                if (!ds) {
                    continue
                }
                crossSeriesData.push({
                    series: originalSeries(series, entry.series.key),
                    datum: ds,
                })
            }
            onBoxClick({
                series: originalSeries(series, data.series.key),
                seriesIndex: data.seriesIndex,
                dataIndex: data.dataIndex,
                label: data.label,
                datum,
                crossSeriesData,
            })
        },
        [onBoxClick, series]
    )

    return (
        <Chart<BoxPlotAdaptedMeta<Meta>>
            series={adaptedSeries}
            labels={labels}
            config={{ ...config, axisOrientation: 'vertical', xTickFormatter }}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={renderTooltip}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
        >
            {children}
        </Chart>
    )
}

interface DrawSeriesBoxesOptions {
    meanRadius: number
    whiskerCapRatio: number
    boxStrokeWidth: number
}

function drawSeriesBoxes(
    ctx: CanvasRenderingContext2D,
    boxes: BoxRect[],
    color: string,
    { meanRadius, whiskerCapRatio, boxStrokeWidth }: DrawSeriesBoxesOptions
): void {
    const fillColor = hexToRgba(color, 0.25)
    const meanFillColor = hexToRgba(color, 0.5)
    for (const box of boxes) {
        drawBox(ctx, box, {
            color,
            fillColor,
            meanFillColor,
            meanRadius,
            whiskerCapRatio,
            lineWidth: boxStrokeWidth,
        })
    }
}

function originalSeries<Meta>(series: BoxPlotSeries<Meta>[], key: string): BoxPlotSeries<Meta> {
    return series.find((s) => s.key === key) ?? series[0]
}

/** Best-effort hex/rgb-to-rgba conversion. Returns the original color string unchanged when
 *  the input isn't a recognised hex/rgb/rgba color — the canvas will attempt to use it as-is. */
function hexToRgba(color: string, alpha: number): string {
    if (color.startsWith('#')) {
        let hex = color.slice(1)
        if (hex.length === 3) {
            hex = hex
                .split('')
                .map((c) => c + c)
                .join('')
        }
        if (hex.length === 6) {
            const r = parseInt(hex.slice(0, 2), 16)
            const g = parseInt(hex.slice(2, 4), 16)
            const b = parseInt(hex.slice(4, 6), 16)
            if ([r, g, b].every((n) => Number.isFinite(n))) {
                return `rgba(${r}, ${g}, ${b}, ${alpha})`
            }
        }
    }
    if (color.startsWith('rgb(')) {
        return color.replace('rgb(', 'rgba(').replace(')', `, ${alpha})`)
    }
    if (color.startsWith('rgba(')) {
        return color.replace(/,\s*[0-9.]+\)$/, `, ${alpha})`)
    }
    return color
}
