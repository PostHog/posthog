import React, { useCallback, useMemo } from 'react'

import { drawBoxes, drawBoxHighlight, drawGrid, type DrawContext } from '../../core/canvas-renderer'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { dimColor } from '../../core/color-utils'
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
import { computeBoxRect, computeSeriesBoxes } from './computeBoxLayout'
import type { BoxPlotDatum, BoxPlotSeries } from './types'
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

/** Meta attached to the inner adapter `Series` we hand to the `Chart` base — carries the
 *  original six-number summaries indexed by x-position, plus any user-supplied meta. Exported
 *  so consumers with a custom `tooltip` can read the original datum back out of
 *  `entry.series.meta?.datums?.[ctx.dataIndex]`. */
export interface BoxPlotAdaptedMeta<Meta = unknown> {
    datums: (BoxPlotDatum | null)[]
    user?: Meta
}

/** Tooltip context handed to consumer-supplied `tooltip` callbacks. Same shape as
 *  `TooltipContext` but with the `BoxPlotAdaptedMeta` `Meta` parameter baked in so consumers
 *  don't have to redeclare it. */
export type BoxPlotTooltipContext<Meta = unknown> = TooltipContext<BoxPlotAdaptedMeta<Meta>>

/** Chart-level config. `axisOrientation` is always vertical for BoxPlot — there's no
 *  horizontal mode — so it's omitted from the consumer-visible config to avoid silently
 *  ignored values. */
export interface BoxPlotConfig extends Omit<ChartConfig, 'axisOrientation'> {
    /** Mean marker radius in CSS pixels. Defaults to 3. */
    meanRadius?: number
    /** Whisker cap width as a fraction of the box width. Defaults to 0.6. */
    whiskerCapRatio?: number
    /** Box outline / whisker stroke width. Defaults to 1.5. */
    boxStrokeWidth?: number
}

export interface BoxPlotClickData<Meta = unknown> {
    /** The *first visible series* at the clicked column — matches BarChart's `onPointClick`
     *  contract. In grouped mode this is **not necessarily the series under the cursor**: when
     *  the user clicks series B's sub-band, `series` is still A. The product layer should
     *  narrow via `crossSeriesData` + the cursor x if it needs the precise box. */
    series: BoxPlotSeries<Meta>
    /** Index of `series` in the input `series` array (first-visible, not under-cursor). */
    seriesIndex: number
    /** Index along the x-axis (into `labels`). */
    dataIndex: number
    /** The x-axis label at this index. */
    label: string
    /** The six-number summary on `series` at this column. */
    datum: BoxPlotDatum
    /** All visible boxes at this column, in render order, for cross-series comparisons. */
    crossSeriesData: { series: BoxPlotSeries<Meta>; datum: BoxPlotDatum }[]
}

export interface BoxPlotProps<Meta = unknown> {
    series: BoxPlotSeries<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: BoxPlotConfig
    /** Optional custom tooltip. Receives the adapter `TooltipContext`; consumers can read
     *  the original datum back out via `entry.series.meta?.datums?.[ctx.dataIndex]`. */
    tooltip?: (ctx: BoxPlotTooltipContext<Meta>) => React.ReactNode
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
        meanRadius = 3,
        whiskerCapRatio = 0.6,
        boxStrokeWidth = 1.5,
    } = config ?? {}

    const grouped = series.filter((s) => !s.visibility?.excluded).length > 1

    const adaptedSeries = useMemo<Series<BoxPlotAdaptedMeta<Meta>>[]>(
        () =>
            series.map((s) => ({
                key: s.key,
                label: s.label,
                color: s.color,
                data: Array.from({ length: labels.length }, (_, i) => {
                    const datum = s.data[i]
                    return datum && Number.isFinite(datum.median) ? datum.median : Number.NaN
                }),
                meta: { datums: s.data, user: s.meta },
                visibility: s.visibility,
            })),
        [series, labels.length]
    )

    /** Synthetic series carrying min/max samples so the y-domain spans every whisker, not just
     *  the medians on `adaptedSeries.data`. Fed to `createBarScales` (as `stackedSeries`) for
     *  the d3 scale and to `Chart` (as `valueRangeSeries`) for `useChartMargins` tick sizing —
     *  one source, two call sites. */
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
                if (Number.isFinite(datum.min)) {
                    mins.push(datum.min)
                }
                if (Number.isFinite(datum.max)) {
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

    const { datumsByKey, seriesByKey } = useMemo(() => {
        const datums = new Map<string, (BoxPlotDatum | null)[]>()
        const seriesMap = new Map<string, BoxPlotSeries<Meta>>()
        for (const s of series) {
            datums.set(s.key, s.data)
            seriesMap.set(s.key, s)
        }
        return { datumsByKey: datums, seriesByKey: seriesMap }
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
                drawBoxes(ctx, boxes, {
                    color: s.color,
                    fillColor: dimColor(s.color, 0.25),
                    meanFillColor: dimColor(s.color, 0.5),
                    meanRadius,
                    whiskerCapRatio,
                    lineWidth: boxStrokeWidth,
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

            // Same band-axis hit-test as BarChart's hover layer — anchors the highlight to
            // whichever group slot the cursor lines up with. `seriesKeysAtCursor` is now
            // band-only, so we only materialise the full `BoxRect` for hit series in the loop.
            const hits = seriesKeysAtCursor<Meta>({
                series,
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
                drawBoxHighlight(ctx, box, dimColor(s.color, 0.25))
                drewAny = true
            }
            return drewAny
        },
        [series]
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
            const primarySeries = seriesByKey.get(data.series.key)
            if (!datum || !primarySeries) {
                return
            }
            const crossSeriesData: BoxPlotClickData<Meta>['crossSeriesData'] = []
            for (const entry of data.crossSeriesData) {
                const ds = entry.series.meta?.datums?.[data.dataIndex]
                const origin = seriesByKey.get(entry.series.key)
                if (!ds || !origin) {
                    continue
                }
                crossSeriesData.push({ series: origin, datum: ds })
            }
            onBoxClick({
                series: primarySeries,
                seriesIndex: data.seriesIndex,
                dataIndex: data.dataIndex,
                label: data.label,
                datum,
                crossSeriesData,
            })
        },
        [onBoxClick, seriesByKey]
    )

    return (
        <Chart<BoxPlotAdaptedMeta<Meta>>
            series={adaptedSeries}
            labels={labels}
            config={{ ...config, axisOrientation: 'vertical' }}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={renderTooltip}
            onPointClick={onPointClick}
            valueRangeSeries={valueRangeSeries.length > 0 ? valueRangeSeries : undefined}
            className={className}
            dataAttr={dataAttr}
        >
            {children}
        </Chart>
    )
}
