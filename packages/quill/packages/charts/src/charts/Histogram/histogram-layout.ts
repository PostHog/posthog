import { scaleLinear, scaleLog } from 'd3-scale'

import { autoFormatterFor, buildValueScale, yTickCountForHeight } from '../../core/scales'
import type { D3YScale, SeriesValueRange } from '../../core/scales'
import type { ChartDimensions } from '../../core/types'
import { measureLabelWidth } from '../../utils/text-measure'

export type HistogramScaleType = 'linear' | 'log'

export interface HistogramEdges {
    start: number
    end: number
}

/** A bin after {@link prepareHistogramBins}: sorted, non-overlapping, with a positive width. */
export interface PreparedHistogramBin<Source = HistogramEdges> extends HistogramEdges {
    /** Index of the bin in the caller's array, for re-aligning per-bin data. */
    sourceIndex: number
    source: Source
}

/** One drawn column. Bins narrower than a device pixel merge with their neighbors into one column,
 *  so none drops out of the drawing, hover, or selection. `x0`/`x1` are device-pixel snapped. */
export interface HistogramLayoutBin extends HistogramEdges {
    /** First prepared bin in the column. Hover and the chart's labels use it. */
    index: number
    /** Last prepared bin in the column. Equals `index` unless sub-pixel bins merged. */
    lastIndex: number
    x0: number
    x1: number
    /** Half-open range of this column's entries in `HistogramLayout.segments`. */
    segmentStart: number
    segmentEnd: number
}

export interface HistogramSegment {
    /** Position of the column in `HistogramLayout.bins`. */
    column: number
    seriesIndex: number
    x: number
    y: number
    width: number
    height: number
}

export interface HistogramXTick {
    value: number
    text: string
    x: number
}

export interface HistogramLayout {
    xScale: D3YScale
    yScale: D3YScale
    xScaleType: HistogramScaleType
    /** Drawn columns in ascending x order. On a log axis, bins ending at or below zero are absent. */
    bins: HistogramLayoutBin[]
    /** Position in `bins` of the column holding each prepared bin, or -1 when the bin is not drawn. */
    columnOf: number[]
    segments: HistogramSegment[]
    /** Visible-series total per prepared bin, drawable or not. */
    totals: number[]
    grandTotal: number
    yTicks: number[]
    xTicks: HistogramXTick[]
    /** Pixel of the value-axis floor that bars grow from. */
    baselineY: number
}

export interface HistogramLayoutInput {
    bins: HistogramEdges[]
    /** Per-series counts aligned with `bins`. Excluded series draw nothing and count toward nothing. */
    series: { data: number[]; excluded?: boolean }[]
    dimensions: ChartDimensions
    xScaleType?: HistogramScaleType
    yScaleType?: HistogramScaleType
    xTickFormatter?: (value: number) => string
    /** Floor (px) on the height of a non-empty bin, so a lone sample next to a tall bin stays visible. */
    minBarHeight?: number
    /** Device pixel ratio that bar edges snap to, so adjacent bars share an exact edge. */
    pixelRatio?: number
}

// Bars this wide or wider get a 1px gutter (half a pixel off each side), as in Observable Plot.
// Narrower bars fill edge to edge so a 1,000-bin histogram reads as a continuous shape.
const BAR_GUTTER_MIN_WIDTH = 3
const BAR_GUTTER = 0.5
const X_TICK_SPACING_PX = 80
const X_TICK_LABEL_PADDING = 12
const LOG_TICK_MANTISSAS = [1, 5, 2]

function finiteCount(value: number | undefined): number {
    return typeof value === 'number' && isFinite(value) && value > 0 ? value : 0
}

/** Per-bin total across visible series. Non-finite and negative counts count as zero. */
export function histogramTotals(series: { data: number[]; excluded?: boolean }[], binCount: number): number[] {
    const totals = Array.from({ length: binCount }, () => 0)
    for (const s of series) {
        if (s.excluded) {
            continue
        }
        for (let i = 0; i < binCount; i++) {
            totals[i] += finiteCount(s.data[i])
        }
    }
    return totals
}

/** Sorts bins by their edges, drops non-finite or empty ones, and trims an overlapping bin's start to
 *  the previous bin's end, so the layout can binary-search columns that never overlap. */
export function prepareHistogramBins<Source extends HistogramEdges>(
    bins: readonly Source[]
): PreparedHistogramBin<Source>[] {
    const candidates: PreparedHistogramBin<Source>[] = []
    bins.forEach((bin, sourceIndex) => {
        if (bin && isFinite(bin.start) && isFinite(bin.end) && bin.end > bin.start) {
            candidates.push({ start: bin.start, end: bin.end, sourceIndex, source: bin })
        }
    })
    candidates.sort((a, b) => a.start - b.start || a.end - b.end)

    const prepared: PreparedHistogramBin<Source>[] = []
    let previousEnd = -Infinity
    for (const bin of candidates) {
        const start = Math.max(bin.start, previousEnd)
        if (bin.end <= start) {
            continue
        }
        prepared.push(start === bin.start ? bin : { ...bin, start })
        previousEnd = bin.end
    }
    return prepared
}

/** On a log axis a bin that starts at or below zero (the usual `[0, first edge)` latency bucket) has
 *  no left edge, so it borrows the width ratio of the first positive bin. */
function logDrawStarts(bins: HistogramEdges[]): number[] {
    const firstPositive = bins.find((bin) => bin.start > 0)
    const ratio = firstPositive ? firstPositive.end / firstPositive.start : 10
    return bins.map((bin) => (bin.start > 0 ? bin.start : bin.end / ratio))
}

function buildXScale(
    bins: HistogramEdges[],
    scaleType: HistogramScaleType,
    range: [number, number]
): { scale: D3YScale; drawStarts: number[]; drawable: boolean[] } {
    if (scaleType === 'log') {
        const drawStarts = logDrawStarts(bins)
        const drawable = bins.map((bin) => bin.end > 0)
        const first = drawable.indexOf(true)
        const domain: [number, number] = first >= 0 ? [drawStarts[first], bins[bins.length - 1].end] : [1, 10]
        return { scale: scaleLog().domain(domain).range(range).clamp(true), drawStarts, drawable }
    }
    const domain: [number, number] = bins.length ? [bins[0].start, bins[bins.length - 1].end] : [0, 1]
    return {
        scale: scaleLinear().domain(domain).range(range),
        drawStarts: bins.map((bin) => bin.start),
        drawable: bins.map(() => true),
    }
}

function snapTo(pixelRatio: number): (value: number) => number {
    return (value) => Math.round(value * pixelRatio) / pixelRatio
}

function linearTickCandidates(scale: D3YScale, plotWidth: number): number[] {
    const count = Math.max(2, Math.min(10, Math.floor(plotWidth / X_TICK_SPACING_PX)))
    return scale.ticks?.(count) ?? []
}

/** Greedy left-to-right pass that keeps each label clear of the previous one. */
function dropCollidingTicks(ticks: HistogramXTick[]): HistogramXTick[] {
    const kept: HistogramXTick[] = []
    let lastRight = -Infinity
    for (const tick of ticks) {
        const half = measureLabelWidth(tick.text) / 2
        if (tick.x - half >= lastRight + X_TICK_LABEL_PADDING) {
            kept.push(tick)
            lastRight = tick.x + half
        }
    }
    return kept
}

/** Placed ticks whose label fits inside the chart, since the wrapper clips anything past its edge. */
function toTicks(
    values: number[],
    scale: D3YScale,
    format: (value: number) => string,
    containerWidth: number
): HistogramXTick[] {
    return values
        .map((value) => ({ value, text: format(value), x: scale(value) }))
        .filter((tick) => {
            const half = measureLabelWidth(tick.text) / 2
            return isFinite(tick.x) && tick.x - half >= 0 && tick.x + half <= containerWidth
        })
        .sort((a, b) => a.x - b.x)
}

/** Log ticks in 1-2-5 decade steps. Every decade fits first (thinned if it must), then all the 5s,
 *  then all the 2s, so an axis never shows a lone 5 between bare decades. */
function logTicks(
    scale: D3YScale,
    plotWidth: number,
    containerWidth: number,
    formatter: ((value: number) => string) | undefined
): HistogramXTick[] {
    const [lo, hi] = scale.domain()
    const levels: number[][] = LOG_TICK_MANTISSAS.map(() => [])
    for (let exponent = Math.floor(Math.log10(lo)); exponent <= Math.ceil(Math.log10(hi)); exponent++) {
        LOG_TICK_MANTISSAS.forEach((mantissa, level) => {
            // toPrecision strips float residue such as 2 × 10⁻³ = 0.0020000000000000005.
            const value = Number((mantissa * Math.pow(10, exponent)).toPrecision(12))
            if (value >= lo * (1 - 1e-9) && value <= hi * (1 + 1e-9)) {
                levels[level].push(value)
            }
        })
    }
    const allValues = levels.flat()
    if (allValues.length < 2) {
        const fallback = linearTickCandidates(scale, plotWidth)
        return dropCollidingTicks(toTicks(fallback, scale, formatter ?? autoFormatterFor(fallback), containerWidth))
    }
    const format = formatter ?? autoFormatterFor(allValues)
    let accepted = toTicks(levels[0], scale, format, containerWidth)
    let kept = dropCollidingTicks(accepted)
    for (let level = 1; level < levels.length && kept.length === accepted.length; level++) {
        const next = toTicks([...accepted.map((tick) => tick.value), ...levels[level]], scale, format, containerWidth)
        const nextKept = dropCollidingTicks(next)
        if (nextKept.length !== next.length) {
            break
        }
        accepted = next
        kept = nextKept
    }
    return kept
}

function computeXTicks(
    scale: D3YScale,
    scaleType: HistogramScaleType,
    dimensions: ChartDimensions,
    formatter: ((value: number) => string) | undefined
): HistogramXTick[] {
    if (scaleType === 'log') {
        return logTicks(scale, dimensions.plotWidth, dimensions.width, formatter)
    }
    const ticks = linearTickCandidates(scale, dimensions.plotWidth)
    return dropCollidingTicks(toTicks(ticks, scale, formatter ?? autoFormatterFor(ticks), dimensions.width))
}

function valueRangeOf(totals: number[]): SeriesValueRange {
    let max = -Infinity
    let minPositive = Infinity
    for (const total of totals) {
        max = Math.max(max, total)
        if (total > 0) {
            minPositive = Math.min(minPositive, total)
        }
    }
    return totals.length
        ? { min: 0, max, minPositive, count: totals.length }
        : { min: Infinity, max, minPositive, count: 0 }
}

/** Whole-number ticks when every count is whole, since "2.5 requests" reads as a bug. A log axis
 *  also drops its floor tick, which `niceLogDomain` puts a decade below the smallest count. */
function countTicks(
    yScale: D3YScale,
    tickCount: number,
    floor: number,
    scaleType: HistogramScaleType,
    totals: number[]
): number[] {
    const ticks = yScale.ticks?.(tickCount) ?? []
    if (scaleType === 'log' && floor > 0) {
        return ticks.filter((tick) => tick > floor)
    }
    if (!totals.every((total) => Number.isInteger(total))) {
        return ticks
    }
    const whole = ticks.filter((tick) => Number.isInteger(tick))
    return whole.length >= 2 ? whole : ticks
}

interface PendingColumn extends HistogramEdges {
    index: number
    lastIndex: number
    x0: number
    x1: number
}

/** Groups drawable bins into columns at least one device pixel wide. */
function buildColumns(
    bins: HistogramEdges[],
    drawStarts: number[],
    drawable: boolean[],
    xScale: D3YScale,
    snap: (value: number) => number,
    minWidth: number
): PendingColumn[] {
    const columns: PendingColumn[] = []
    let pending: PendingColumn | null = null
    // A sub-pixel remainder joins the column it touches, or else draws one device pixel wide.
    const flush = (column: PendingColumn): void => {
        const previous = columns[columns.length - 1]
        if (column.x1 > column.x0) {
            columns.push(column)
        } else if (previous && previous.x1 >= column.x0) {
            columns[columns.length - 1] = { ...previous, lastIndex: column.lastIndex, end: column.end }
        } else {
            columns.push({ ...column, x1: column.x0 + minWidth })
        }
    }
    for (let index = 0; index < bins.length; index++) {
        const bin = bins[index]
        if (!drawable[index]) {
            continue
        }
        const x0 = snap(xScale(drawStarts[index]))
        const x1 = snap(xScale(bin.end))
        if (!isFinite(x0) || !isFinite(x1)) {
            continue
        }
        if (pending && x0 > pending.x1) {
            flush(pending)
            pending = null
        }
        const previous: PendingColumn | null = pending
        const current: PendingColumn = previous
            ? { ...previous, lastIndex: index, end: bin.end, x1: Math.max(previous.x1, x1) }
            : { index, lastIndex: index, start: bin.start, end: bin.end, x0, x1 }
        if (current.x1 > current.x0) {
            flush(current)
            pending = null
        } else {
            pending = current
        }
    }
    if (pending) {
        flush(pending)
    }
    return columns
}

function sumRange(values: number[], from: number, to: number): number {
    let sum = 0
    for (let i = from; i <= to; i++) {
        sum += finiteCount(values[i])
    }
    return sum
}

/** Places every bin on a numeric x axis at its real edges and stacks its series counts. */
export function computeHistogramLayout({
    bins,
    series,
    dimensions,
    xScaleType = 'linear',
    yScaleType = 'linear',
    xTickFormatter,
    minBarHeight = 0,
    pixelRatio = 1,
}: HistogramLayoutInput): HistogramLayout {
    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotBottom = plotTop + plotHeight
    const ratio = pixelRatio > 0 ? pixelRatio : 1
    const snap = snapTo(ratio)
    const visibleSeries = series.map((s, seriesIndex) => ({ ...s, seriesIndex })).filter((s) => !s.excluded)

    const totals = histogramTotals(series, bins.length)
    const grandTotal = totals.reduce((sum, total) => sum + total, 0)

    const { scale: xScale, drawStarts, drawable } = buildXScale(bins, xScaleType, [plotLeft, plotLeft + plotWidth])
    const columns = buildColumns(bins, drawStarts, drawable, xScale, snap, 1 / ratio)
    const columnTotals = columns.map((column) => sumRange(totals, column.index, column.lastIndex))

    const tickCount = yTickCountForHeight(plotHeight)
    const yScale = buildValueScale({
        range: valueRangeOf(columnTotals),
        valueRange: [plotBottom, plotTop],
        tickCount,
        scaleType: yScaleType,
    })
    const yDomainFloor = Math.min(...(yScale.domain() as number[]))
    const baselineY = snap(yScale(yDomainFloor))
    const valueY = (value: number): number => (value <= yDomainFloor ? baselineY : snap(yScale(value)))

    const columnOf = Array.from({ length: bins.length }, () => -1)
    const layoutBins: HistogramLayoutBin[] = []
    const segments: HistogramSegment[] = []
    columns.forEach((column, position) => {
        for (let i = column.index; i <= column.lastIndex; i++) {
            columnOf[i] = position
        }
        const { x0, x1 } = column
        const inset = x1 - x0 >= BAR_GUTTER_MIN_WIDTH ? BAR_GUTTER : 0
        const columnSegments: HistogramSegment[] = []
        let bottom = 0
        for (const s of visibleSeries) {
            const count = sumRange(s.data, column.index, column.lastIndex)
            if (count === 0) {
                continue
            }
            const yBottom = valueY(bottom)
            bottom += count
            const yTop = valueY(bottom)
            columnSegments.push({
                column: position,
                seriesIndex: s.seriesIndex,
                x: x0 + inset,
                y: yTop,
                width: x1 - x0 - inset * 2,
                height: yBottom - yTop,
            })
        }
        const top = columnSegments[columnSegments.length - 1]
        if (top && baselineY - top.y < minBarHeight) {
            const floored = baselineY - minBarHeight
            top.height += top.y - floored
            top.y = floored
        }
        const segmentStart = segments.length
        segments.push(...columnSegments.filter((segment) => segment.height > 0 && segment.width > 0))
        layoutBins.push({ ...column, segmentStart, segmentEnd: segments.length })
    })

    return {
        xScale,
        yScale,
        xScaleType,
        bins: layoutBins,
        columnOf,
        segments,
        totals,
        grandTotal,
        yTicks: countTicks(yScale, tickCount, yDomainFloor, yScaleType, columnTotals),
        xTicks: computeXTicks(xScale, xScaleType, dimensions, xTickFormatter),
        baselineY,
    }
}

/** Position in `bins` of the first column whose right edge is past `x`, or `bins.length`. */
function firstColumnEndingAfter(bins: HistogramLayoutBin[], x: number): number {
    let lo = 0
    let hi = bins.length
    while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (bins[mid].x1 > x) {
            hi = mid
        } else {
            lo = mid + 1
        }
    }
    return lo
}

/** Position in `bins` of the last column whose left edge is before `x`, or -1. */
function lastColumnStartingBefore(bins: HistogramLayoutBin[], x: number): number {
    let lo = 0
    let hi = bins.length
    while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (bins[mid].x0 < x) {
            lo = mid + 1
        } else {
            hi = mid
        }
    }
    return lo - 1
}

/** The column under `x`, or undefined over a gap or outside every bin. */
export function histogramColumnAtPixel(
    layout: Pick<HistogramLayout, 'bins'>,
    x: number
): HistogramLayoutBin | undefined {
    const column = layout.bins[firstColumnEndingAfter(layout.bins, x)]
    return column && column.x0 <= x ? column : undefined
}

/** Snaps a dragged pixel span outward to whole columns: the first column whose right edge is past
 *  the span's left edge through the last column whose left edge is before its right edge. A span that
 *  ends exactly on a column edge excludes the column beyond it. Null when the span covers no bin. */
export function snapPixelRangeToBins(
    layout: Pick<HistogramLayout, 'bins'>,
    xPixel0: number,
    xPixel1: number
): { first: HistogramLayoutBin; last: HistogramLayoutBin } | null {
    const first = firstColumnEndingAfter(layout.bins, Math.min(xPixel0, xPixel1))
    const last = lastColumnStartingBefore(layout.bins, Math.max(xPixel0, xPixel1))
    if (first >= layout.bins.length || last < 0 || first > last) {
        return null
    }
    return { first: layout.bins[first], last: layout.bins[last] }
}

/** Pixel span of a value range, clamped to the x domain. Null when it misses the domain entirely. */
export function histogramRangeToPixels(
    layout: Pick<HistogramLayout, 'xScale'>,
    range: { min: number; max: number }
): { x0: number; x1: number } | null {
    const [lo, hi] = layout.xScale.domain()
    const min = Math.max(range.min, lo)
    const max = Math.min(range.max, hi)
    if (!(max > min)) {
        return null
    }
    return { x0: layout.xScale(min), x1: layout.xScale(max) }
}

/** Value below which `percentile`% of the samples fall, interpolated linearly inside the bin that
 *  crosses it, as Prometheus' `histogram_quantile` does. `bins` must be sorted and non-overlapping
 *  (see {@link prepareHistogramBins}), with `totals` aligned to them. Undefined when the bins hold no
 *  samples. */
export function estimateHistogramPercentile(
    bins: HistogramEdges[],
    totals: number[],
    percentile: number
): number | undefined {
    const grandTotal = totals.reduce((sum, total) => sum + finiteCount(total), 0)
    if (grandTotal <= 0 || !isFinite(percentile)) {
        return undefined
    }
    const target = (Math.min(Math.max(percentile, 0), 100) / 100) * grandTotal
    let cumulative = 0
    let lastEnd: number | undefined
    for (let i = 0; i < bins.length; i++) {
        const count = finiteCount(totals[i])
        if (count === 0) {
            continue
        }
        if (cumulative + count >= target) {
            return bins[i].start + ((target - cumulative) / count) * (bins[i].end - bins[i].start)
        }
        cumulative += count
        lastEnd = bins[i].end
    }
    return lastEnd
}
