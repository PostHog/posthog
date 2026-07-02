import { computeBarAtIndex, computeBarTrackRect } from '../../../core/bar-layout'
import type { BarRect } from '../../../core/canvas-renderer'
import { type BarScaleSet, groupedBandSlot, type StackedBand } from '../../../core/scales'
import type { BandSlot, Series } from '../../../core/types'
import { DEFAULT_Y_AXIS_ID } from '../../../core/types'

export type BarLayout = 'stacked' | 'grouped' | 'percent'

export function isStackedLayout(layout: BarLayout): boolean {
    return layout !== 'grouped'
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

/** True when the cursor sits beyond a series' per-bar track ceiling — the blank, inert region above a
 *  capped `trackData` track (a funnel compare bar's volume gap). False when the series has no ceiling
 *  at this bar (the track spans the whole axis). Callers establish band-axis containment and that the
 *  cursor is already outside the bar's own fill before calling. */
export function cursorBeyondTrackCeiling(
    series: { trackData?: number[] },
    bar: BarRect,
    scales: BarScaleSet,
    point: { x: number; y: number },
    isHorizontal: boolean
): boolean {
    const ceiling = series.trackData?.[bar.dataIndex]
    if (ceiling == null) {
        return false
    }
    const ceilingPixel = scales.value(ceiling)
    if (!isFinite(ceilingPixel)) {
        return false
    }
    // Track grows from the value baseline (range start) to the ceiling; beyond it is the blank gap.
    const [axisBaseline = 0] = scales.value.range()
    return !barContainsPoint(computeBarTrackRect(bar, axisBaseline, ceilingPixel, isHorizontal), point)
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
}

export interface BarAtCursor<S> {
    series: S
    bar: BarRect
}

/** Yields the renderable `{ series, bar }` for every visible series at `(label, dataIndex)`.
 *  Single source of truth shared by drawHover, tooltip narrowing, and click routing —
 *  encapsulates visibility skip, stacked-band lookup, and `computeBarAtIndex`. */
export function* barsAtCursor<S extends Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'>>(
    args: Omit<BarsAtCursorArgs, 'series'> & { series: readonly S[] }
): Generator<BarAtCursor<S>> {
    const { series, label, dataIndex, scales, layout, isHorizontal, stackedData, topStackedKeyByAxis } = args
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        const stackedBand = stackedData?.get(s.key)
        const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
        const isTopOfStack = topStackedKeyByAxis.get(axisId) === s.key
        const bar = computeBarAtIndex({
            series: s as unknown as Series,
            label,
            dataIndex,
            scales,
            layout,
            isHorizontal,
            stackedBand,
            isTopOfStack,
        })
        if (bar) {
            yield { series: s, bar }
        }
    }
}

/** True when the cursor sits in a grouped bar's inert volume gap — lined up on the band axis with a bar
 *  whose capped `trackData` ceiling it has passed (a funnel compare period's blank space above its
 *  track). Such a position takes no hover, tooltip, highlight, or click. Non-grouped layouts, and bars
 *  whose track spans the full axis, are never a gap. */
export function cursorInInertTrackGap(
    args: Omit<BarsAtCursorArgs, 'series'> & {
        // `trackData` beyond the base pick so the ceiling check sees each series' cap.
        series: readonly Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data' | 'trackData'>[]
        cursor: { x: number; y: number }
    }
): boolean {
    const { cursor, isHorizontal, layout, scales } = args
    if (layout !== 'grouped') {
        return false
    }
    for (const { series: s, bar } of barsAtCursor(args)) {
        if (!barContainsPointOnBandAxis(bar, cursor, isHorizontal)) {
            continue
        }
        // The cursor lines up with this bar's column — it's in the gap only when it's both outside the
        // bar's own fill and beyond that bar's track ceiling.
        return (
            cursorOutsideBarFillExtent(bar, cursor, isHorizontal) &&
            cursorBeyondTrackCeiling(s, bar, scales, cursor, isHorizontal)
        )
    }
    return false
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
    for (const { series: s, bar } of barsAtCursor(args)) {
        if (barContainsPointOnBandAxis(bar, cursor, isHorizontal)) {
            hits.add(s.key)
        }
        if (strictHit == null && barContainsPoint(bar, cursor)) {
            strictHit = s.key
        }
    }
    return { hits, strictHit }
}

/** Resolve the grouped bar nearest the cursor along the band axis, returning its `{ x, width }`
 *  slot. `bandAxisCursor` is the cursor coordinate on the band axis (x for vertical charts).
 *  Returns undefined for non-grouped layouts (no `group` scale) or an unknown label.
 *  A `scaleBand` is uniform, so the nearest slot index is the cursor's offset from the first
 *  slot center divided by the step — O(1), no scan over the domain. */
export function groupedBandSlotAtCursor(
    scales: BarScaleSet,
    label: string,
    bandAxisCursor: number
): BandSlot | undefined {
    const { band, group } = scales
    const start = band(label)
    const domain = group?.domain()
    if (!group || start == null || !domain?.length) {
        return undefined
    }
    const step = group.step()
    const firstCenter = (group(domain[0]) ?? 0) + group.bandwidth() / 2
    const rawIndex = Math.round((bandAxisCursor - start - firstCenter) / step)
    const index = Math.max(0, Math.min(domain.length - 1, rawIndex))
    return groupedBandSlot(scales, label, domain[index])
}

/** Pixel coordinate of a bar's baseline (value-0) edge — the side the bar grows from. */
function barBaseline(bar: BarRect, isHorizontal: boolean): number {
    return isHorizontal ? bar.x : bar.y + bar.height
}

/** Visible stacked segment under the cursor — last-drawn bar whose rect contains it.
 *  Also returns the next-smaller extent (the far edge of the bar that overdraws this
 *  segment's near side); callers clip the highlight rect there so hover preserves z-order.
 *
 *  Overdraw only occurs in the sparse "overlap" layout where sibling segments share a
 *  baseline (each series drawn from value 0, smallest on top). Properly stacked segments
 *  each start where the previous ends, so no sibling shares the hovered segment's baseline
 *  and `nextSmallerExtent` is 0 — the segment's own rect is already the visible slice. */
export function findVisibleStackedSegment<S extends Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'>>(
    args: Omit<BarsAtCursorArgs, 'series' | 'label' | 'dataIndex'> & {
        series: readonly S[]
        labels: readonly string[]
        hoveredLabel: string
        cursor: { x: number; y: number }
    }
): { series: S; bar: BarRect; dataIndex: number; nextSmallerExtent: number } | null {
    const { labels, hoveredLabel, cursor, isHorizontal } = args
    let visible: { series: S; bar: BarRect; dataIndex: number; extent: number; baseline: number } | null = null
    const candidates: { extent: number; baseline: number }[] = []
    for (let dataIndex = 0; dataIndex < labels.length; dataIndex++) {
        if (labels[dataIndex] !== hoveredLabel) {
            continue
        }
        for (const { series: s, bar } of barsAtCursor({ ...args, label: labels[dataIndex], dataIndex })) {
            const extent = isHorizontal ? bar.width : bar.height
            if (extent <= 0) {
                continue
            }
            const baseline = barBaseline(bar, isHorizontal)
            candidates.push({ extent, baseline })
            if (!barContainsPoint(bar, cursor)) {
                continue
            }
            // Overwrite so the last-drawn (smallest, painted on top) candidate wins.
            visible = { series: s, bar, dataIndex, extent, baseline }
        }
    }
    if (!visible) {
        return null
    }
    // Largest sibling that shares this baseline and is smaller — i.e. overdraws the
    // segment's near side. Non-overlapping siblings sit on different baselines and are skipped.
    const BASELINE_EPSILON = 0.5
    const nextSmallerExtent = candidates.reduce(
        (max, c) =>
            Math.abs(c.baseline - visible!.baseline) <= BASELINE_EPSILON && c.extent < visible!.extent && c.extent > max
                ? c.extent
                : max,
        0
    )
    return { series: visible.series, bar: visible.bar, dataIndex: visible.dataIndex, nextSmallerExtent }
}
