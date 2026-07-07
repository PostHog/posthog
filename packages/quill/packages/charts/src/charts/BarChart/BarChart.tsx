import React, { useCallback, useMemo, useRef } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import { bandCenter, type BarChartPrivate, groupedBarCenter } from '../../core/bar-layout'
import { Chart } from '../../core/Chart'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useLatest } from '../../core/hooks/useLatest'
import {
    buildSegmentResolveValue,
    buildStackedBottomValue,
    buildStackedPositionValue,
    computeDivergingStackData,
    computePercentStackData,
    computeStackData,
    computeTopStackedKeyByAxis,
    createBarScales,
    type StackedBand,
    toYAxisScales,
    yTickCountForHeight,
} from '../../core/scales'
import type {
    BarChartConfig,
    ChartDimensions,
    ChartDrawArgs,
    ChartScales,
    ChartTheme,
    CreateScalesFn,
    DrawHoverResult,
    PointClickData,
    ResolvedSeries,
    Series,
    TooltipContext,
} from '../../core/types'
import { resolveAxisLines } from '../../core/types'
import { BarTooltip } from './BarTooltip'
import { computeWrapperMinHeight, HORIZONTAL_MIN_BAND_SIZE_DEFAULT } from './utils/bar-config'
import { cursorInInertTrackGap, groupedBandSlotAtCursor } from './utils/bars-under-cursor'
import { drawBarChartStatic, drawBarHoverItems } from './utils/draw-bar-chart'
import { resolveBarHoverItems } from './utils/resolve-bar-hover'
import { resolveClickedBarSeries } from './utils/resolve-clicked-bar-series'

export interface BarChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: BarChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function BarChart<Meta = unknown>({ onError, ...rest }: BarChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <BarChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function BarChartInner<Meta = unknown>({
    series,
    labels,
    config,
    theme,
    tooltip,
    onPointClick,
    className,
    dataAttr,
    children,
}: Omit<BarChartProps<Meta>, 'onError'>): React.ReactElement {
    const {
        yScaleType = 'linear',
        showGrid = false,
        showAxisLines = false,
        barLayout = 'stacked',
        axisOrientation = 'vertical',
        xTickFormatter,
        barCornerRadius = 0,
        yAxes: configYAxes,
    } = config ?? {}
    const { x: xAxisLine, y: yAxisLine } = resolveAxisLines(showAxisLines)
    const axisLines = useMemo(() => ({ x: xAxisLine, y: yAxisLine }), [xAxisLine, yAxisLine])
    const {
        track: trackConfig = false,
        shadow: barShadow,
        divergingStack = false,
        maxBandRange,
        bandPadding,
        minBandSize,
        fitToHeight = false,
        valueDomain,
        valuePadding,
        roundStackEnds = false,
        fillStyle: barFillStyle = 'flat',
    } = config?.bars ?? {}
    const isHorizontal = axisOrientation === 'horizontal'
    const barTrack = trackConfig !== false
    const barTrackHover = trackConfig === true || (typeof trackConfig === 'object' && trackConfig.hover !== false)

    const { visibleSeries, legendProps } = useChartLegend(series, theme, config?.legend)

    const resolvedMinBandSize = minBandSize ?? (isHorizontal ? HORIZONTAL_MIN_BAND_SIZE_DEFAULT : 0)
    const wrapperMinHeight = useMemo(
        () =>
            computeWrapperMinHeight({
                isHorizontal,
                fitToHeight,
                resolvedMinBandSize,
                labels,
            }),
        [isHorizontal, fitToHeight, resolvedMinBandSize, labels]
    )

    const stackedData = useMemo((): Map<string, StackedBand> | undefined => {
        if (barLayout === 'percent') {
            return computePercentStackData(visibleSeries, labels)
        }
        if (barLayout === 'stacked') {
            return divergingStack
                ? computeDivergingStackData(visibleSeries, labels)
                : computeStackData(visibleSeries, labels)
        }
        return undefined
    }, [barLayout, visibleSeries, labels, divergingStack])

    // Cap rounding is per-axis: buildStackData stacks each yAxisId independently, so each
    // axis has its own topmost visible series. Iteration order matches d3.stack's key order,
    // so the last write per axis is that axis's top layer.
    const topStackedKeyByAxis = useMemo<Map<string, string>>(
        () => (barLayout === 'grouped' ? new Map() : computeTopStackedKeyByAxis(visibleSeries)),
        [barLayout, visibleSeries]
    )

    const chartConfig = useMemo<BarChartConfig>(() => {
        const base = { ...config, isPercent: barLayout === 'percent' }
        if (barLayout !== 'percent' || config?.yTickFormatter) {
            return base
        }
        return {
            ...base,
            yTickFormatter: (v: number) => `${Math.round(v * 100)}%`,
        }
    }, [config, barLayout])

    const createScales: CreateScalesFn = useCallback(
        (coloredSeries: ResolvedSeries[], scaleLabels: string[], dimensions: ChartDimensions): ChartScales => {
            // For stacked/percent, the value-axis domain must reflect cumulative sums, not
            // individual series ranges — pass a synthetic series whose data is each layer's top.
            // Diverging stacks also need each layer's bottom so negative columns extend the domain
            // below 0 (the bottom of a positive-only stack is always 0, but a diverging stack with
            // negative values pushes the bottom below 0).
            let stackedSeries: Series[] | undefined
            if (stackedData && barLayout === 'stacked') {
                stackedSeries = coloredSeries.flatMap((s) => {
                    const band = stackedData.get(s.key)
                    if (!band) {
                        return [s]
                    }
                    if (divergingStack) {
                        return [
                            { ...s, data: band.top },
                            {
                                ...s,
                                key: `${s.key}__bottom`,
                                data: band.bottom,
                            },
                        ]
                    }
                    return [{ ...s, data: band.top }]
                })
            }

            const d3Scales = createBarScales(coloredSeries, scaleLabels, dimensions, {
                scaleType: yScaleType,
                barLayout,
                axisOrientation,
                stackedSeries,
                maxBandRange,
                bandPadding,
                fitToHeight,
                minBandSize: resolvedMinBandSize,
                valueDomain,
                valuePadding,
                axes: configYAxes,
            })

            const tickAxisLength = isHorizontal ? dimensions.plotWidth : dimensions.plotHeight
            const yTickCount = yTickCountForHeight(tickAxisLength)

            // Expose per-axis scales so AxisLabels renders the right-hand axis and the tooltip /
            // value-label overlays resolve each series against its own axis.
            const yAxes = d3Scales.yAxes ? toYAxisScales(d3Scales.yAxes, yTickCount) : undefined

            // Stash the raw d3 scales in the private slot so drawStatic/drawHover/click routing
            // can read them from the committed ChartScales — every render gets a self-contained
            // object, which avoids strict-mode / concurrent-rendering races.
            const barChartPrivate: BarChartPrivate = { __barChart: d3Scales }

            // For horizontal, expose the value scale as `y` (since AxisLabels horizontal mode
            // calls `scales.y(tick)` for x-pixel positioning of value ticks).
            // For vertical, `y` is the value scale on the y-axis.
            return {
                x: (label: string, seriesKey?: string) => {
                    if (seriesKey != null && barLayout === 'grouped') {
                        const xForSeries = groupedBarCenter(d3Scales, label, seriesKey)
                        if (xForSeries != null) {
                            return xForSeries
                        }
                    }
                    return bandCenter(d3Scales, label)
                },
                y: (value: number) => d3Scales.value(value),
                yTicks: () => d3Scales.value.ticks?.(yTickCount) ?? [],
                yAxes,
                // Width of the rendered bar content within the band. In grouped mode the
                // bars sit inside group outer padding, so `band.bandwidth()` overshoots
                // the rightmost bar's right edge and anchors the tooltip in empty space.
                extent: () => {
                    if (isHorizontal) {
                        return undefined
                    }
                    const groupScale = d3Scales.group
                    if (barLayout === 'grouped' && groupScale) {
                        const domain = groupScale.domain()
                        if (domain.length > 0) {
                            const firstOffset = groupScale(domain[0]) ?? 0
                            const lastOffset = groupScale(domain[domain.length - 1]) ?? 0
                            const contentExtent = lastOffset + groupScale.bandwidth() - firstOffset
                            if (contentExtent > 0) {
                                return contentExtent
                            }
                        }
                    }
                    return d3Scales.band.bandwidth()
                },
                // Anchor the tooltip on the grouped bar under the cursor instead of the whole
                // group. Vertical grouped only; other layouts fall back to the band-center anchor.
                bandSlotAtCursor: (label: string, cursor: { x: number; y: number }) =>
                    isHorizontal || barLayout !== 'grouped'
                        ? undefined
                        : groupedBandSlotAtCursor(d3Scales, label, cursor.x),
                _private: barChartPrivate,
            }
        },
        [
            yScaleType,
            barLayout,
            axisOrientation,
            stackedData,
            isHorizontal,
            divergingStack,
            maxBandRange,
            bandPadding,
            fitToHeight,
            resolvedMinBandSize,
            valueDomain,
            valuePadding,
            configYAxes,
        ]
    )

    const drawStatic = useCallback(
        (args: ChartDrawArgs) =>
            drawBarChartStatic(args, {
                barLayout,
                isHorizontal,
                showGrid,
                axisLines,
                xTickFormatter,
                stackedData,
                topStackedKeyByAxis,
                roundStackEnds,
                barCornerRadius,
                barTrack,
                barShadow,
                barFillStyle,
            }),
        [
            showGrid,
            axisLines,
            stackedData,
            barLayout,
            isHorizontal,
            topStackedKeyByAxis,
            roundStackEnds,
            barCornerRadius,
            barTrack,
            xTickFormatter,
            barShadow,
            barFillStyle,
        ]
    )

    // Restart the fade on bar → track moves (same hoverIndex, different visible state).
    const lastHoverKeyRef = useRef<string | null>(null)

    const drawHover = useCallback(
        (args: ChartDrawArgs): DrawHoverResult => {
            const { ctx, scales, hoverIndex, hoverProgress, resetHoverFade } = args
            const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
            if (!d3Scales || hoverIndex < 0) {
                lastHoverKeyRef.current = null
                return false
            }
            const resolved = resolveBarHoverItems(args, d3Scales, {
                barLayout,
                isHorizontal,
                stackedData,
                topStackedKeyByAxis,
                roundStackEnds,
                barTrackHover,
            })
            if (!resolved) {
                lastHoverKeyRef.current = null
                return false
            }
            // Key on the bar-vs-track composition so a bar → track move at the same hoverIndex
            // still restarts the fade.
            const currentKey = `${hoverIndex}:${resolved.composition}`
            let alpha = hoverProgress
            if (currentKey !== lastHoverKeyRef.current) {
                alpha = resetHoverFade()
                lastHoverKeyRef.current = currentKey
            }
            drawBarHoverItems(ctx, d3Scales, resolved, {
                alpha,
                barCornerRadius,
                barTrack,
                isHorizontal,
            })
            return true
        },
        [
            stackedData,
            barLayout,
            isHorizontal,
            topStackedKeyByAxis,
            roundStackEnds,
            barCornerRadius,
            barTrack,
            barTrackHover,
        ]
    )

    // Show each series's own segment value (resolveValue) but anchor the tooltip/value labels
    // at the stacked top (resolvePositionValue) so a stacked bar doesn't read as a running total.
    const resolveValue = useMemo(() => buildSegmentResolveValue(stackedData), [stackedData])
    const resolvePositionValue = useMemo(() => buildStackedPositionValue(stackedData), [stackedData])
    const resolveBottomValue = useMemo(() => buildStackedBottomValue(stackedData), [stackedData])

    const seriesRef = useLatest(visibleSeries)
    const labelsRef = useLatest(labels)

    // Bars sharing a band slot — rewrite the click payload to the series actually under the
    // cursor so drop-off fillers and per-breakdown segments route correctly.
    const wrapClickData = useCallback(
        (clickData: PointClickData<Meta>, scales: ChartScales): PointClickData<Meta> => {
            const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
            if (!d3Scales) {
                return clickData
            }
            return (
                resolveClickedBarSeries({
                    clickData,
                    scales: d3Scales,
                    barLayout,
                    isHorizontal,
                    stackedData,
                    topStackedKeyByAxis,
                    series: seriesRef.current,
                    labels: labelsRef.current,
                }) ?? clickData
            )
        },
        [barLayout, isHorizontal, stackedData, topStackedKeyByAxis, seriesRef, labelsRef]
    )

    // A capped track's blank volume gap (funnel compare) is inert: veto the hover there so the tooltip,
    // pointer cursor, highlight, and click are all suppressed. Only wired when a series declares a
    // `trackData` ceiling — with or without a drawn track (stacked funnel bars cap their interactive
    // extent without one).
    const seriesHasTrackCeiling = useMemo(() => visibleSeries.some((s) => Array.isArray(s.trackData)), [visibleSeries])

    const resolveHoverIndex = useCallback(
        (index: number, cursor: { x: number; y: number }, scales: ChartScales): number => {
            const d3Scales = (scales._private as BarChartPrivate | undefined)?.__barChart
            if (!d3Scales) {
                return index
            }
            return cursorInInertTrackGap({
                series: seriesRef.current,
                label: labelsRef.current[index],
                dataIndex: index,
                scales: d3Scales,
                layout: barLayout,
                isHorizontal,
                stackedData,
                topStackedKeyByAxis,
                cursor,
            })
                ? -1
                : index
        },
        [barLayout, isHorizontal, stackedData, topStackedKeyByAxis, seriesRef, labelsRef]
    )

    const chart = (
        <Chart
            series={visibleSeries}
            labels={labels}
            config={chartConfig}
            theme={theme}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={(ctx) => (
                <BarTooltip<Meta>
                    ctx={ctx}
                    userTooltip={tooltip}
                    allSeries={visibleSeries}
                    stackedData={stackedData}
                    topStackedKeyByAxis={topStackedKeyByAxis}
                    layout={barLayout}
                    isHorizontal={isHorizontal}
                    tooltipConfig={config?.tooltip}
                />
            )}
            onPointClick={onPointClick}
            wrapClickData={onPointClick ? wrapClickData : undefined}
            resolveHoverIndex={seriesHasTrackCeiling ? resolveHoverIndex : undefined}
            className={className}
            dataAttr={dataAttr}
            resolveValue={resolveValue}
            resolvePositionValue={resolvePositionValue}
            resolveBottomValue={resolveBottomValue}
        >
            {children}
        </Chart>
    )

    // Always wrap — switching shape (axisOrientation, empty labels) would otherwise remount Chart.
    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-bar-legend">
            <div className="flex flex-col flex-1" style={{ minHeight: wrapperMinHeight }}>
                {chart}
            </div>
        </ChartLegend>
    )
}
