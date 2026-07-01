import { bisector } from 'd3-array'

import { barColorAt } from './color-utils'
import type {
    BandSlot,
    ChartDimensions,
    DragRect,
    PointClickData,
    ResolvedSeries,
    ResolveValueFn,
    TooltipContext,
    YAxisScale,
} from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

export type { DragRect } from './types'

export interface LabelPosition {
    x: number
    index: number
}

const positionBisector = bisector<LabelPosition, number>((d) => d.x).center

/** Builds the (x, index) lookup table for hit-testing. O(N) — call once per (labels, xScale) change
 *  and feed the result into {@link findNearestIndexFromPositions} on each mousemove. */
export function buildLabelPositions(labels: string[], xScale: (label: string) => number | undefined): LabelPosition[] {
    const positions: LabelPosition[] = []
    for (let i = 0; i < labels.length; i++) {
        const x = xScale(labels[i])
        if (x != null && isFinite(x)) {
            positions.push({ x, index: i })
        }
    }
    return positions
}

/** Binary search over precomputed positions. O(log N) per call. */
export function findNearestIndexFromPositions(mouseX: number, positions: LabelPosition[]): number {
    if (positions.length === 0) {
        return -1
    }
    const nearestIdx = positionBisector(positions, mouseX)
    return positions[Math.max(0, Math.min(nearestIdx, positions.length - 1))].index
}

export function findNearestIndex(
    mouseX: number,
    labels: string[],
    xScale: (label: string) => number | undefined
): number {
    if (labels.length === 0) {
        return -1
    }
    return findNearestIndexFromPositions(mouseX, buildLabelPositions(labels, xScale))
}

export function isInPlotArea(mouseX: number, mouseY: number, dimensions: ChartDimensions): boolean {
    return (
        mouseX >= dimensions.plotLeft &&
        mouseX <= dimensions.plotLeft + dimensions.plotWidth &&
        mouseY >= dimensions.plotTop &&
        mouseY <= dimensions.plotTop + dimensions.plotHeight
    )
}

// Returns null when fewer than 2 distinct labels are spanned.
export function dragRectToLabelRange(
    rect: DragRect,
    labelPositions: LabelPosition[]
): { startIndex: number; endIndex: number } | null {
    if (labelPositions.length < 2) {
        return null
    }
    const lo = Math.min(rect.x0, rect.x1)
    const hi = Math.max(rect.x0, rect.x1)
    const startIndex = findNearestIndexFromPositions(lo, labelPositions)
    const endIndex = findNearestIndexFromPositions(hi, labelPositions)
    if (startIndex < 0 || endIndex < 0 || startIndex === endIndex) {
        return null
    }
    const [s, e] = startIndex < endIndex ? [startIndex, endIndex] : [endIndex, startIndex]
    return { startIndex: s, endIndex: e }
}

export function buildTooltipContext<Meta = unknown>(
    dataIndex: number,
    series: ResolvedSeries<Meta>[],
    labels: string[],
    xScale: (label: string) => number | undefined,
    yScale: (value: number) => number,
    canvasBounds: DOMRect,
    resolveValue: ResolveValueFn,
    yAxes?: Record<string, YAxisScale>,
    /** Returned `position.{x,y}` are canvas-pixel coordinates regardless of orientation. */
    interactionAxis: 'x' | 'y' = 'x',
    hoverPosition: { x: number; y: number } | null = null,
    /** Resolves the value used to *anchor* the tooltip per series. Defaults to `resolveValue`.
     *  Stacked charts pass the stacked-top resolver here so the anchor lands at the visual top
     *  of each segment while each tooltip row still shows its own value via `resolveValue`. */
    resolvePositionValue: ResolveValueFn = resolveValue,
    /** Resolves the stacked *bottom* value for each series. When provided, yPixelBottom is
     *  stored alongside yPixel so findClosestSeriesKey can use range containment rather than
     *  distance — cursor inside [yPixel, yPixelBottom] wins exactly at the segment boundary. */
    resolveBottomValue?: ResolveValueFn,
    /** Optional horizontal data-extent centered on the categorical axis position — bar charts
     *  pass band width so the tooltip can anchor at the band edge instead of its center. */
    positionExtent?: number,
    /** Optional per-bar anchor for grouped layouts — overrides the band-axis center and extent
     *  so the tooltip anchors on the hovered bar rather than the whole group. */
    bandSlot?: BandSlot
): TooltipContext<Meta> | null {
    if (dataIndex < 0 || dataIndex >= labels.length) {
        return null
    }

    const label = labels[dataIndex]
    const bandPixel = xScale(label)
    if (bandPixel == null) {
        return null
    }

    const seriesData: TooltipContext<Meta>['seriesData'] = []
    const valuePixels: number[] = []
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        // `resolveValue` is the value shown to the user (the segment); `resolvePositionValue`
        // is where to anchor (the stacked top). They diverge only for stacked charts.
        // A gap (`data[i]` non-finite) draws no point/bar, so don't fabricate a `0` row for it —
        // skip it the same way the renderer does.
        const rawValue = s.data[dataIndex]
        const seriesValueScale = yAxes?.[s.yAxisId ?? DEFAULT_Y_AXIS_ID]?.scale ?? yScale
        const px = seriesValueScale(resolvePositionValue(s, dataIndex))
        if (isFinite(px)) {
            valuePixels.push(px)
        }
        if (s.visibility?.tooltip !== false && rawValue != null && isFinite(rawValue)) {
            // A per-bar series carries each bar's identity in `bars[i]` — surface it so the tooltip
            // reads the right color/meta/label rather than the shared series-level ones.
            const bar = s.bars?.[dataIndex]
            const entrySeries = bar ? { ...s, meta: bar.meta ?? s.meta, label: bar.label ?? s.label } : s
            const segmentValue = resolveValue(s, dataIndex)
            // Expose the segment bottom pixel so findClosestSeriesKey can do range containment
            // testing (is cursor between top and bottom?) instead of distance-to-midpoint, which
            // breaks when adjacent segments differ greatly in size.
            const yPixelBottom =
                resolveBottomValue && isFinite(px)
                    ? (() => {
                          const b = seriesValueScale(resolveBottomValue(s, dataIndex))
                          return isFinite(b) ? b : undefined
                      })()
                    : undefined
            seriesData.push({
                series: entrySeries,
                value: segmentValue,
                color: barColorAt(s, dataIndex),
                yPixel: isFinite(px) ? px : undefined,
                yPixelBottom,
            })
        }
    }

    // Anchor at the visual "tip" of the data column at this hover index — topmost in vertical
    // mode, rightmost in horizontal mode.
    let valueAnchor = 0
    if (valuePixels.length > 0) {
        valueAnchor = interactionAxis === 'y' ? Math.max(...valuePixels) : Math.min(...valuePixels)
    }

    const bandAxisCoord = bandSlot ? bandSlot.x + bandSlot.width / 2 : bandPixel
    const position: TooltipContext<Meta>['position'] =
        interactionAxis === 'y' ? { x: valueAnchor, y: bandAxisCoord } : { x: bandAxisCoord, y: valueAnchor }
    const extentWidth = bandSlot?.width ?? positionExtent
    if (extentWidth != null && extentWidth > 0) {
        position.width = extentWidth
    }

    return {
        dataIndex,
        label,
        seriesData,
        position,
        hoverPosition,
        canvasBounds,
        isPinned: false,
    }
}

export function buildPointClickData<Meta = unknown>(
    dataIndex: number,
    series: ResolvedSeries<Meta>[],
    labels: string[],
    resolveValue: ResolveValueFn,
    // Required — callers pass `null` explicitly when cursor isn't available. No implicit default
    // because losing the cursor silently breaks downstream click routing.
    cursor: { x: number; y: number } | null
): PointClickData<Meta> | null {
    if (dataIndex < 0 || dataIndex >= labels.length) {
        return null
    }

    const visibleSeries = series.filter((s) => !s.visibility?.excluded)
    if (visibleSeries.length === 0) {
        return null
    }

    const firstSeries = visibleSeries[0]

    return {
        seriesIndex: series.indexOf(firstSeries),
        dataIndex,
        series: firstSeries,
        value: resolveValue(firstSeries, dataIndex),
        label: labels[dataIndex],
        crossSeriesData: visibleSeries.map((s) => ({
            series: s,
            value: resolveValue(s, dataIndex),
        })),
        cursor,
    }
}
