import annotationPlugin from 'chartjs-plugin-annotation'
import clsx from 'clsx'
import { useMemo, useRef, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { Popover } from '@posthog/lemon-ui'

import { Chart, ScaleOptions, TooltipModel } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { useChart } from 'lib/hooks/useChart'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { hexToRGBA } from 'lib/utils/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'

import { LemonSkeleton } from '../lemon-ui/LemonSkeleton'

// Register once at module load. Chart.register is idempotent so re-registers (eg. by
// AlertHistoryChart, which also uses the annotation plugin) are safe.
Chart.register(annotationPlugin)

const HIGHLIGHT_COLOR = '#8f8f8f'

export interface SparklineReferenceLine {
    /** Y-axis value the dashed line is drawn at, in the same units as the series data. */
    value: number
    /** Color name from `vars.scss` (e.g. 'danger'). @default 'danger' */
    color?: string
    /** Optional label to anchor at the end of the line (shown only when provided). */
    label?: string
    /** Where to anchor the optional label. @default 'end' */
    labelPosition?: 'start' | 'center' | 'end'
}

export interface SparklineTimeSeries {
    name: string
    values: number[]
    /** Check vars.scss for available colors. @default 'muted' */
    color?: string
    hoverColor?: string
}

export type AnyScaleOptions = ScaleOptions<'linear' | 'logarithmic' | 'time' | 'timeseries' | 'category'>

export interface SparklineProps {
    /** Either a list of numbers for a muted graph or an array of time series */
    data: number[] | SparklineTimeSeries[]
    /** Check vars.scss for available colors. @default 'muted' */
    color?: string
    colors?: string[]
    /** A name for each time series. */
    name?: string
    names?: string[]
    /** A label for each datapoint. */
    labels?: string[]
    /** @default 'bar' */
    type?: 'bar' | 'line'
    /** Whether the Y-axis maximum should be indicated in the graph. @default true */
    maximumIndicator?: boolean
    /** A skeleton is shown during loading. */
    loading?: boolean
    /** Update the X-axis scale. */
    withXScale?: (x: AnyScaleOptions) => AnyScaleOptions
    /** Update the Y-axis scale. */
    withYScale?: (y: AnyScaleOptions) => AnyScaleOptions
    /** Render a label for the tooltip. */
    renderLabel?: (label: string) => string
    className?: string
    onSelectionChange?: (selection: { startIndex: number; endIndex: number }) => void
    /** Maximum number of series to show in tooltip. @default 8 */
    tooltipRowCutoff?: number
    /** Hide series with zero values from tooltip. @default false */
    hideZerosInTooltip?: boolean
    /** Sort tooltip items by count (descending). @default false */
    sortTooltipByCount?: boolean
    /** Optional horizontal dashed reference lines (thresholds, goals, limits). */
    referenceLines?: SparklineReferenceLine[]
    /** Format the per-series tooltip value. Defaults to `humanFriendlyNumber`. */
    renderTooltipValue?: (value: number) => string
    /**
     * X-axis value range to highlight as a translucent box behind the bars. Values are
     * in the x-axis's own units: epoch ms for a time scale (positioned with sub-bar
     * precision), or a label for a category scale. Used to mirror an external selection
     * (e.g. the rows currently visible in a paired virtualized list) onto the chart.
     * Callers pass an already-ordered `xMin <= xMax`; pass `null`/`undefined` to clear.
     */
    highlightedRange?: { xMin: number | string; xMax: number | string } | null
    /**
     * Bar indices that are still being ingested (incomplete). Those bars render with a faded
     * diagonal-hatch fill, and hovering one adds `tooltip` to the hover tooltip. Used to flag the
     * most recent bucket(s) when ingestion hasn't caught up. Pass `null`/`undefined` or an empty
     * `indices` array to clear.
     */
    incompleteBars?: { indices: number[]; tooltip?: string } | null
}

/**
 * Build a faded diagonal-hatch CanvasPattern for an incomplete bar: a translucent fill of the series
 * colour overlaid with hatch lines, so the bar reads as "still loading" while keeping its colour.
 */
function createHashedPattern(color: string): CanvasPattern | string {
    const size = 6
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d')
    if (!ctx) {
        return color
    }
    ctx.fillStyle = hexToRGBA(color, 0.25)
    ctx.fillRect(0, 0, size, size)
    ctx.strokeStyle = hexToRGBA(color, 0.6)
    ctx.lineWidth = 1
    // Three offset diagonals so the hatch tiles seamlessly across the bar.
    ctx.beginPath()
    ctx.moveTo(0, size)
    ctx.lineTo(size, 0)
    ctx.moveTo(-1, 1)
    ctx.lineTo(1, -1)
    ctx.moveTo(size - 1, size + 1)
    ctx.lineTo(size + 1, size - 1)
    ctx.stroke()
    return ctx.createPattern(canvas, 'repeat') ?? color
}

export function Sparkline({
    data,
    color,
    colors,
    name,
    names,
    labels,
    type = 'bar',
    maximumIndicator = true,
    loading = false,
    withXScale,
    withYScale,
    renderLabel,
    onSelectionChange,
    className,
    tooltipRowCutoff,
    hideZerosInTooltip = false,
    sortTooltipByCount = false,
    referenceLines,
    renderTooltipValue,
    highlightedRange,
    incompleteBars,
}: SparklineProps): JSX.Element {
    const tooltipRef = useRef<HTMLDivElement | null>(null)

    const [tooltip, setTooltip] = useState<TooltipModel<'bar'> | null>(null)
    const dragStartRef = useRef<{ index: number; x: number } | null>(null)
    const [isDragging, setIsDragging] = useState(false)

    const incompleteBarSet = useMemo(() => new Set(incompleteBars?.indices ?? []), [incompleteBars])

    const adjustedData: SparklineTimeSeries[] = useMemo(() => {
        const arrayData = Array.isArray(data)
            ? data.length > 0 && typeof data[0] === 'object'
                ? data // array of objects, one per series
                : [data] // array of numbers, turn it into the first series
            : typeof data === 'object'
              ? [data] // first series as an object
              : [[data]] // just a random number... huh
        return arrayData.map((timeseries, index): SparklineTimeSeries => {
            const defaultName =
                names?.[index] || (arrayData.length === 1 ? name || 'Count' : `${name || 'Series'} ${index + 1}`)
            const defaultColor = colors?.[index] || color || 'muted'
            if (typeof timeseries === 'object') {
                if (!Array.isArray(timeseries)) {
                    return {
                        name: timeseries.name || defaultName,
                        color: timeseries.color || defaultColor,
                        values: timeseries.values || [],
                    }
                }
                return {
                    name: defaultName,
                    color: defaultColor,
                    values: timeseries as number[],
                }
            }
            return {
                name: defaultName,
                color: defaultColor,
                values: timeseries ? [timeseries] : [],
            }
        })
    }, [data]) // oxlint-disable-line react-hooks/exhaustive-deps

    const { canvasRef } = useChart({
        getConfig: () => {
            // data should always be provided but React can render this without it,
            // so, fall back to null for safety
            if (data === undefined || data.length === 0) {
                return null
            }
            const defaultXScale: AnyScaleOptions = {
                // X axis not needed in line charts without indicators
                display: type === 'bar' || maximumIndicator,
                bounds: 'data',
                stacked: true,
                ticks: {
                    display: false,
                },
                grid: {
                    drawTicks: false,
                    display: false,
                },
                alignToPixels: true,
            }

            // Make sure reference lines always fit on the chart — Chart.js would otherwise
            // auto-scale to the data only and a threshold above the peak would be clipped.
            const referenceLineMax =
                referenceLines && referenceLines.length > 0 ? Math.max(...referenceLines.map((l) => l.value)) : 0

            const defaultYScale: AnyScaleOptions = {
                // We use the Y axis for the maximum indicator
                display: maximumIndicator,
                bounds: 'data',
                min: 0, // Always starting at 0
                // Headroom above whichever is taller — data or a reference line — so a threshold
                // sitting near the chart top still has room for its label without clipping.
                suggestedMax: referenceLineMax > 0 ? referenceLineMax * 1.2 : 1,
                stacked: true,
                ticks: {
                    includeBounds: true,
                    autoSkip: true,
                    maxTicksLimit: 1, // Only the max
                    align: 'start',
                    callback: (tickValue) =>
                        typeof tickValue === 'number' && tickValue > 0 // Hide the zero tick
                            ? humanFriendlyNumber(tickValue)
                            : null,
                    font: {
                        size: 10,
                        lineHeight: 1,
                    },
                },
                grid: {
                    tickBorderDash: [2],
                    display: true,
                    tickLength: 0,
                },
                border: { display: false },
                alignToPixels: true,
                afterFit: (axis) => {
                    // Remove unnecessary padding
                    axis.paddingTop = 1 // 1px and not 0 to avoid clipping of the grid
                    axis.paddingBottom = 1
                },
            }

            const xScale = withXScale ? withXScale(defaultXScale) : defaultXScale
            const yScale = withYScale ? withYScale(defaultYScale) : defaultYScale

            return {
                type,
                data: {
                    labels: labels || adjustedData[0].values.map((_, i) => `Entry ${i}`),
                    datasets: adjustedData.map((timeseries) => {
                        const seriesColor = getColorVar(timeseries.color || 'muted')
                        const hoverColor = getColorVar(timeseries.hoverColor || timeseries.color || 'muted')
                        // Incomplete (still-ingesting) bars get a faded hatch of the series colour so
                        // they read as "not final" without losing which series they belong to.
                        const hatched = incompleteBarSet.size > 0 ? createHashedPattern(seriesColor) : null
                        const fillFor = (
                            base: string
                        ): typeof base | CanvasPattern | ((ctx: { dataIndex: number }) => string | CanvasPattern) =>
                            hatched
                                ? (ctx: { dataIndex: number }) => (incompleteBarSet.has(ctx.dataIndex) ? hatched : base)
                                : base
                        return {
                            label: timeseries.name,
                            data: timeseries.values,
                            minBarLength: 0,
                            categoryPercentage: 0.9, // Slightly tighter bar spacing than the default 0.8
                            backgroundColor: fillFor(seriesColor),
                            hoverBackgroundColor: fillFor(hoverColor),
                            borderColor: seriesColor,
                            borderWidth: type === 'line' ? 2 : 0,
                            pointRadius: 0,
                            borderRadius: 2,
                        }
                    }),
                },
                options: {
                    scales: {
                        x: xScale,
                        y: yScale,
                    },
                    plugins: {
                        crosshair: false,
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            enabled: false, // Using external tooltip
                            external({ tooltip }) {
                                // We spread it otherwise it just ends up being a reference to the tooltip object
                                setTooltip({ ...tooltip } as TooltipModel<'bar'>)
                            },
                        },
                        ...(() => {
                            const annotations: Record<string, any> = {}

                            if (referenceLines && referenceLines.length > 0) {
                                referenceLines.forEach((line, i) => {
                                    const lineColor = getColorVar(line.color || 'danger')
                                    annotations[`referenceLine${i}`] = {
                                        type: 'line',
                                        yMin: line.value,
                                        yMax: line.value,
                                        borderColor: lineColor,
                                        borderWidth: 1.5,
                                        borderDash: [5, 4],
                                        ...(line.label
                                            ? {
                                                  label: {
                                                      display: true,
                                                      content: line.label,
                                                      position: line.labelPosition || 'end',
                                                      font: { size: 9 },
                                                      color: lineColor,
                                                      backgroundColor: 'transparent',
                                                      // Sit the label just above the line so it doesn't render on top of it.
                                                      // The 20% y-axis headroom set above guarantees it stays inside the chart.
                                                      yAdjust: -8,
                                                  },
                                              }
                                            : {}),
                                    }
                                })
                            }

                            if (highlightedRange && labels && labels.length > 0) {
                                annotations.highlightedRange = {
                                    type: 'box',
                                    xMin: highlightedRange.xMin,
                                    xMax: highlightedRange.xMax,
                                    // Drawn under the bars so the data stays legible.
                                    drawTime: 'beforeDatasetsDraw',
                                    // Faint fill with a stronger border to mark the window edges.
                                    backgroundColor: hexToRGBA(HIGHLIGHT_COLOR, 0.1),
                                    borderColor: hexToRGBA(HIGHLIGHT_COLOR, 0.8),
                                    borderWidth: 1,
                                }
                            }

                            return Object.keys(annotations).length > 0 ? { annotation: { annotations } } : {}
                        })(),
                    },
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        axis: 'x',
                        intersect: false,
                    },
                },
            }
        },
        deps: [
            labels,
            adjustedData,
            withXScale,
            withYScale,
            renderLabel,
            data,
            maximumIndicator,
            type,
            referenceLines,
            highlightedRange,
            incompleteBars,
        ],
    })

    const dataPointCount = adjustedData[0]?.values?.length || 0
    const finalClassName = clsx(
        'relative',
        dataPointCount > 16 ? 'w-64' : dataPointCount > 8 ? 'w-48' : dataPointCount > 4 ? 'w-32' : 'w-24',
        className
    )

    const tooltipVisible = !!(tooltip && tooltip.opacity > 0)
    const toolTipDataPoints = tooltip && tooltip.dataPoints ? tooltip.dataPoints : []

    const hoveredElementX = toolTipDataPoints[0]?.element?.x ?? 0
    const hoveredElementWidth = (toolTipDataPoints[0]?.element as any)?.width ?? 0

    useKeyboardHotkeys({
        escape: {
            action: () => {
                setIsDragging(false)
            },
        },
    })

    useEventListener(
        'mouseup',
        () => {
            if (!isDragging) {
                return
            }

            setIsDragging(false)

            if (!onSelectionChange || !toolTipDataPoints.length || !dragStartRef.current) {
                return
            }

            const startIndex = dragStartRef.current.index
            const endIndex = toolTipDataPoints[0].dataIndex
            dragStartRef.current = null

            if (typeof startIndex !== 'number' || typeof endIndex !== 'number') {
                return
            }

            if (startIndex !== endIndex) {
                onSelectionChange({
                    startIndex: Math.min(startIndex, endIndex),
                    endIndex: Math.max(startIndex, endIndex),
                })
            }
        },
        window,
        [isDragging, onSelectionChange]
    )

    const onMouseDown = (): void => {
        if (!onSelectionChange) {
            return
        }
        setIsDragging(true)
        dragStartRef.current = { index: toolTipDataPoints[0].dataIndex, x: hoveredElementX }
    }

    let selectionLeft = hoveredElementX
    let selectionWidth = 1

    if (isDragging && dragStartRef.current) {
        if (hoveredElementX === dragStartRef.current.x) {
            // If the same we just show it in the middle of the bar
        } else if (hoveredElementX > dragStartRef.current.x) {
            // If we are hovering past where we started we set it to be before the bar and after the next
            selectionLeft = dragStartRef.current.x - hoveredElementWidth / 2
            selectionWidth = hoveredElementX + hoveredElementWidth / 2 - selectionLeft
        } else {
            // If we are hovering before where we started we set it to be after the bar and before the next
            selectionLeft = hoveredElementX - hoveredElementWidth / 2
            selectionWidth = dragStartRef.current.x + hoveredElementWidth / 2 - selectionLeft
        }
    }

    return !loading ? (
        <div className={finalClassName} onMouseDown={onSelectionChange ? onMouseDown : undefined}>
            <canvas ref={canvasRef} />
            <>
                {tooltipVisible && onSelectionChange && (
                    <div className="absolute inset-0 pointer-events-none">
                        <div
                            className="rounded opacity-50 border absolute"
                            style={{
                                left: selectionLeft ?? 0,
                                width: selectionWidth,
                                height: '100%',
                                backgroundColor: 'rgba(0, 0, 0, 0.5)',
                            }}
                        />
                    </div>
                )}
                <Popover
                    visible={tooltipVisible}
                    overlay={
                        <>
                            {incompleteBarSet.has(toolTipDataPoints[0]?.dataIndex) && (
                                <div className="flex items-center gap-1 px-2 pt-1 text-xs text-warning">
                                    <IconWarning className="shrink-0" />
                                    {incompleteBars?.tooltip ?? 'Some logs are still processing'}
                                </div>
                            )}
                            <InsightTooltip
                                embedded
                                hideInspectActorsSection
                                showHeader={!!labels}
                                altTitle={
                                    toolTipDataPoints.length > 0
                                        ? renderLabel
                                            ? renderLabel(toolTipDataPoints[0].label)
                                            : toolTipDataPoints[0].label
                                        : ''
                                }
                                seriesData={toolTipDataPoints
                                    .map((dp, i) => ({
                                        id: i,
                                        dataIndex: 0,
                                        datasetIndex: 0,
                                        order: i,
                                        label: dp.dataset.label,
                                        color: dp.dataset.borderColor as string,
                                        count: (dp.dataset.data?.[dp.dataIndex] as number) || 0,
                                    }))
                                    .filter((item) => !hideZerosInTooltip || item.count > 0)
                                    .sort((a, b) => (sortTooltipByCount ? b.count - a.count : a.order - b.order))}
                                renderSeries={(value) => value}
                                renderCount={(count) => (renderTooltipValue ?? humanFriendlyNumber)(count)}
                                rowCutoff={tooltipRowCutoff}
                            />
                        </>
                    }
                    placement="bottom-start"
                    padded={false}
                >
                    <div ref={tooltipRef} />
                </Popover>
            </>
        </div>
    ) : (
        <LemonSkeleton className={finalClassName} />
    )
}
