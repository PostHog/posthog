import { resolveCssColor } from '../../core/color-utils'
import { yTickCountForHeight } from '../../core/scales'
import type { D3YScale } from '../../core/scales'
import type { ChartDimensions, ChartScales, ResolvedSeries, ScatterMarkerShape } from '../../core/types'
import type { FlatScatterPoint } from './scatter-data'
import { buildScatterAxisScale, domainBounds, resolveXTicks, xTickCountForWidth } from './scatter-scales'
import type { ScatterAxisScale, ScatterXTick } from './scatter-scales'
import type { ScatterSeries } from './types'

export interface ScatterPointPosition {
    /** Global index into the flattened point list. */
    index: number
    /** Which series drew this point, so per-series work (the best-fit line) can group by it. */
    seriesIndex: number
    x: number
    y: number
    radius: number
    color: string
    shape: ScatterMarkerShape
}

/** What the draw, hit-test, and axis-overlay code read back out of `ChartScales._private`, so each
 *  render carries its own self-consistent layout rather than a side-channel ref. */
export interface ScatterLayout {
    xScale: D3YScale
    yScale: D3YScale
    /** Visible, drawable points in ascending x-pixel order, which the hit test binary-searches. */
    positions: ScatterPointPosition[]
    /** Canvas-ready series colors by series index, for per-series chrome (the best-fit line) that has
     *  to match the legend rather than whichever override a marker happens to carry. */
    seriesColors: string[]
    /** Resolved once, so the grid lines, the tick marks, and the labels are the same set. */
    xTicks: ScatterXTick[]
    maxRadius: number
}

interface ScatterChartPrivate {
    __scatter: ScatterLayout
}

export function readScatterLayout(scales: ChartScales): ScatterLayout | undefined {
    return (scales._private as ScatterChartPrivate | undefined)?.__scatter
}

export interface ScatterScalesInput {
    points: FlatScatterPoint[]
    /** Indexed by `FlatScatterPoint.seriesIndex`. */
    seriesStyles: Pick<ScatterSeries, 'pointRadius' | 'shape'>[]
    coloredSeries: ResolvedSeries[]
    dimensions: ChartDimensions
    xAxis: ScatterAxisScale
    yAxis: ScatterAxisScale
    xTickFormatter?: (value: number) => string
    defaultPointRadius: number
    fallbackColor: string
}

export function createScatterScales({
    points,
    seriesStyles,
    coloredSeries,
    dimensions,
    xAxis,
    yAxis,
    xTickFormatter,
    defaultPointRadius,
    fallbackColor,
}: ScatterScalesInput): ChartScales {
    const hidden = new Set(coloredSeries.filter((s) => s.visibility?.excluded).map((s) => s.key))
    const visiblePoints = hidden.size === 0 ? points : points.filter((p) => !hidden.has(p.seriesKey))

    const xTickCount = xTickCountForWidth(dimensions.plotWidth)
    const yTickCount = yTickCountForHeight(dimensions.plotHeight)
    const xScale = buildScatterAxisScale(
        visiblePoints,
        'x',
        [dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth],
        xTickCount,
        xAxis
    )
    const yScale = buildScatterAxisScale(
        visiblePoints,
        'y',
        [dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop],
        yTickCount,
        yAxis
    )
    const [xLow, xHigh] = domainBounds(xScale)
    const [yLow, yHigh] = domainBounds(yScale)

    const positions: ScatterPointPosition[] = []
    const xByIndex = new Array<number | undefined>(points.length)
    let maxRadius = 0
    for (let i = 0; i < points.length; i++) {
        const point = points[i]
        // A pinned domain narrows the chart rather than just its viewport, so a point outside it is
        // dropped from drawing, hit-testing, and the hover halo alike. Left in, a linear scale draws
        // it in the axis gutters and a clamped log scale on the plot edge, at a value it doesn't have.
        if (hidden.has(point.seriesKey) || point.x < xLow || point.x > xHigh || point.y < yLow || point.y > yHigh) {
            continue
        }
        const x = xScale(point.x)
        const y = yScale(point.y)
        if (!isFinite(x) || !isFinite(y)) {
            continue
        }
        xByIndex[i] = x
        const style = seriesStyles[point.seriesIndex]
        const radius = point.radius ?? style?.pointRadius ?? defaultPointRadius
        maxRadius = Math.max(maxRadius, radius)
        positions.push({
            index: i,
            seriesIndex: point.seriesIndex,
            x,
            y,
            radius,
            // Canvas can't resolve `var(--…)`, which a consumer color may still be.
            color: resolveCssColor(point.color ?? coloredSeries[point.seriesIndex]?.color ?? fallbackColor),
            shape: style?.shape ?? 'circle',
        })
    }

    return {
        x: (label: string) => xByIndex[Number(label)],
        y: (value: number) => yScale(value),
        yTicks: () => yScale.ticks?.(yTickCount) ?? [],
        _private: {
            __scatter: {
                xScale,
                yScale,
                positions,
                seriesColors: coloredSeries.map((series) => resolveCssColor(series.color ?? fallbackColor)),
                xTicks: resolveXTicks(xScale, xTickCount, xTickFormatter),
                maxRadius,
            },
        } satisfies ScatterChartPrivate,
    }
}
