import { computeBarAtIndex } from '../../../core/bar-layout'
import type { BarRect } from '../../../core/canvas-renderer'
import type { BarScaleSet, StackedBand } from '../../../core/scales'
import type { Series } from '../../../core/types'
import { DEFAULT_Y_AXIS_ID } from '../../../core/types'

export type BarLayout = 'stacked' | 'grouped' | 'percent'

export function isStackedLayout(layout: BarLayout): boolean {
    return layout !== 'grouped'
}

/** Per-axis, per-index key of the topmost / bottommost non-zero stacked segment. Cap and
 *  baseline rounding for funnel-style stacks must be resolved per band, not per series: a
 *  100% first step has no filler, so its single segment is simultaneously top and bottom. */
export interface StackEdges {
    topKeyAtIndex: Map<string, (string | null)[]>
    bottomKeyAtIndex: Map<string, (string | null)[]>
}

export function computeStackEdges(
    series: readonly Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'>[],
    indexCount: number
): StackEdges {
    const topKeyAtIndex = new Map<string, (string | null)[]>()
    const bottomKeyAtIndex = new Map<string, (string | null)[]>()
    const arrFor = (m: Map<string, (string | null)[]>, axisId: string): (string | null)[] => {
        let arr = m.get(axisId)
        if (!arr) {
            arr = new Array(indexCount).fill(null)
            m.set(axisId, arr)
        }
        return arr
    }
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
        const topArr = arrFor(topKeyAtIndex, axisId)
        const bottomArr = arrFor(bottomKeyAtIndex, axisId)
        for (let i = 0; i < indexCount; i++) {
            const v = s.data[i]
            if (typeof v !== 'number' || !isFinite(v) || v === 0) {
                continue
            }
            // Series iterate bottom → top (d3.stack key order), so the last non-zero write
            // at an index is the top segment; the first is the bottom.
            topArr[i] = s.key
            if (bottomArr[i] == null) {
                bottomArr[i] = s.key
            }
        }
    }
    return { topKeyAtIndex, bottomKeyAtIndex }
}

/** Grouped-layout hit-test that ignores the value axis so a cursor above (or below) a bar still
 *  selects the bar whose band-slot it lines up with. Matches chart.js's `mode: 'point', axis: 'x'`
 *  behaviour — without this, hovering above a short bar in a grouped pair would fail every
 *  per-bar check, fall back to "highlight all", and visually flag both group-mates at once.
 *  Half-open on the trailing edge — matches d3 band-scale slots `[start, start + size)`. */
export function barContainsPointOnBandAxis(
    bar: BarRect,
    point: { x: number; y: number },
    isHorizontal: boolean
): boolean {
    return isHorizontal
        ? point.y >= bar.y && point.y < bar.y + bar.height
        : point.x >= bar.x && point.x < bar.x + bar.width
}

/** Full-rect (both axes) hit-test. Stacked segments share a band slot; the value axis is
 *  what distinguishes them. Half-open on the trailing edge — matches d3 band-scale slots
 *  `[start, start + size)`. */
export function barContainsPoint(bar: BarRect, point: { x: number; y: number }): boolean {
    return point.x >= bar.x && point.x < bar.x + bar.width && point.y >= bar.y && point.y < bar.y + bar.height
}

/** True when the cursor is in the bar's band slot but outside its filled value extent —
 *  the strict complement of {@link barContainsPointOnBandAxis} on the value axis. Used
 *  to distinguish track-region hover from bar-region hover. Caller is expected to have
 *  already established band-axis containment. */
export function cursorOutsideBarFillExtent(
    bar: BarRect,
    point: { x: number; y: number },
    isHorizontal: boolean
): boolean {
    return isHorizontal
        ? point.x < bar.x || point.x > bar.x + bar.width
        : point.y < bar.y || point.y > bar.y + bar.height
}

export interface BarsAtCursorArgs {
    series: readonly Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'>[]
    label: string
    dataIndex: number
    scales: BarScaleSet
    layout: BarLayout
    isHorizontal: boolean
    stackedData?: Map<string, StackedBand>
    topStackedKeyByAxis: Map<string, string>
    /** When present, cap/baseline rounding is resolved per band from the visible non-zero
     *  stack (funnel-style) so hover highlights match the rounded static bars. */
    stackEdges?: StackEdges
    /** Round the baseline-side corners of the bottom-of-stack segment. Only honored with `stackEdges`. */
    roundStackBaseline?: boolean
}

export interface BarAtCursor<S> {
    series: S
    bar: BarRect
}

/** Yields the renderable `{ series, bar }` for every visible series at `(label, dataIndex)`.
 *  Single source of truth shared by drawHover, tooltip narrowing, and click routing —
 *  encapsulates visibility skip, stacked-band lookup, and `computeBarAtIndex`. */
export function* iterBarsAtCursor<S extends Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'>>(
    args: Omit<BarsAtCursorArgs, 'series'> & { series: readonly S[] }
): Generator<BarAtCursor<S>> {
    const { series, label, dataIndex, scales, layout, isHorizontal, stackedData, topStackedKeyByAxis, stackEdges } =
        args
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        const stackedBand = stackedData?.get(s.key)
        const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
        const isTopOfStack = topStackedKeyByAxis.get(axisId) === s.key
        let capRounded: boolean | undefined
        let baseRounded: boolean | undefined
        if (stackEdges && isStackedLayout(layout)) {
            capRounded = stackEdges.topKeyAtIndex.get(axisId)?.[dataIndex] === s.key
            baseRounded =
                args.roundStackBaseline === true && stackEdges.bottomKeyAtIndex.get(axisId)?.[dataIndex] === s.key
        }
        const bar = computeBarAtIndex({
            series: s as unknown as Series,
            label,
            dataIndex,
            scales,
            layout,
            isHorizontal,
            stackedBand,
            isTopOfStack,
            capRounded,
            baseRounded,
        })
        if (bar) {
            yield { series: s, bar }
        }
    }
}

export interface ResolveBarsAtCursorResult {
    /** Series keys whose bar slot contains the cursor on the band axis (every stacked segment). */
    hits: Set<string>
    /** Series key whose full rect contains the cursor, or `null`. Used to single out a
     *  stacked segment for tooltip ordering and click routing. */
    strictHit: string | null
}

/** Single pass that does both band-axis containment (used by stacked tooltips to list every
 *  segment sharing the slot) and full-rect containment (the one segment under the cursor). */
export function resolveBarsAtCursor(
    args: BarsAtCursorArgs & { cursor: { x: number; y: number } }
): ResolveBarsAtCursorResult {
    const { cursor, isHorizontal } = args
    const hits = new Set<string>()
    let strictHit: string | null = null
    for (const { series: s, bar } of iterBarsAtCursor(args)) {
        if (barContainsPointOnBandAxis(bar, cursor, isHorizontal)) {
            hits.add(s.key)
        }
        if (strictHit == null && barContainsPoint(bar, cursor)) {
            strictHit = s.key
        }
    }
    return { hits, strictHit }
}

/** Value-axis interval [near, far] of a bar, regardless of orientation. */
function valueAxisExtentRange(bar: BarRect, isHorizontal: boolean): [number, number] {
    return isHorizontal ? [bar.x, bar.x + bar.width] : [bar.y, bar.y + bar.height]
}

/** Visible stacked segment under the cursor — last-drawn bar whose rect contains it.
 *  Also returns the next-smaller extent (the far edge of the bar that overdraws this
 *  segment's near side); callers clip the highlight rect there so hover preserves z-order.
 *  Only segments that actually *overlap* the visible one count — in a sparse/aggregated
 *  overlap layout every segment is drawn from the baseline (nested), so a smaller one paints
 *  over this segment's near side; in a proper adjacent stack (funnels) the neighbours sit
 *  beside it and must not clip its highlight. */
export function findVisibleStackedSegment<S extends Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'>>(
    args: Omit<BarsAtCursorArgs, 'series' | 'label' | 'dataIndex'> & {
        series: readonly S[]
        labels: readonly string[]
        hoveredLabel: string
        cursor: { x: number; y: number }
    }
): { series: S; bar: BarRect; dataIndex: number; nextSmallerExtent: number } | null {
    const { labels, hoveredLabel, cursor, isHorizontal } = args
    let visible: { series: S; bar: BarRect; dataIndex: number; extent: number } | null = null
    const candidates: { extent: number; range: [number, number] }[] = []
    for (let dataIndex = 0; dataIndex < labels.length; dataIndex++) {
        if (labels[dataIndex] !== hoveredLabel) {
            continue
        }
        for (const { series: s, bar } of iterBarsAtCursor({ ...args, label: labels[dataIndex], dataIndex })) {
            const extent = isHorizontal ? bar.width : bar.height
            if (extent <= 0) {
                continue
            }
            candidates.push({ extent, range: valueAxisExtentRange(bar, isHorizontal) })
            if (!barContainsPoint(bar, cursor)) {
                continue
            }
            // Overwrite so the last-drawn (smallest, painted on top) candidate wins.
            visible = { series: s, bar, dataIndex, extent }
        }
    }
    if (!visible) {
        return null
    }
    const [visNear, visFar] = valueAxisExtentRange(visible.bar, isHorizontal)
    // Largest overdrawing segment: smaller extent (drawn on top) AND a real pixel overlap with
    // the visible slice. Adjacent stack neighbours only touch at an edge, so they don't count.
    const nextSmallerExtent = candidates.reduce((max, c) => {
        if (c.extent >= visible!.extent || c.extent <= max) {
            return max
        }
        const overlaps = c.range[0] < visFar && visNear < c.range[1]
        return overlaps ? c.extent : max
    }, 0)
    return { series: visible.series, bar: visible.bar, dataIndex: visible.dataIndex, nextSmallerExtent }
}
