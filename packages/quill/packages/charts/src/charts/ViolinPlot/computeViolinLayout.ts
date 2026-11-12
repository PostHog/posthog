import { computeBandSlot } from '../../core/band-slot'
import type { BarScaleSet } from '../../core/scales'
import type { ViolinPlotDatum, ViolinRect, ViolinSummary } from './types'

/** Number of points the density is sampled at. The outline is drawn as a polyline through them. */
const DENSITY_SAMPLES = 96
/** The density is estimated from at most this many values. Larger groups are thinned evenly, so
 *  the cost of a violin stays bounded however many observations it holds. */
const MAX_DENSITY_VALUES = 1000
/** At most this many observation markers are drawn per violin, for the same reason. */
const MAX_DRAWN_POINTS = 500
/** Kernel window, in bandwidths. Gaussian weight beyond it is negligible. */
const KERNEL_REACH = 4
/** How far the outline extends past the extreme values, in bandwidths, so the tips taper. */
const TAIL_BANDWIDTHS = 2
/** Share of the slot half-width the widest part of a violin fills. */
const VIOLIN_WIDTH_RATIO = 0.95
/** Total sideways spread of the observation markers, as a share of the slot width. */
const POINT_SPREAD_RATIO = 0.16
/** The smallest bandwidth, as a share of the value-axis span, so a group of identical values
 *  still draws a visible bump. */
const MIN_BANDWIDTH_RATIO = 0.02
const GOLDEN_RATIO_CONJUGATE = 0.6180339887498949

interface PreparedViolin {
    /** Finite observations, ascending, in the space the density is estimated in. */
    sorted: number[]
    summary: ViolinSummary
}

const linearCache = new WeakMap<ViolinPlotDatum, PreparedViolin | null>()
const logCache = new WeakMap<ViolinPlotDatum, PreparedViolin | null>()

function quantileOfSorted(sorted: readonly number[], q: number): number {
    const position = (sorted.length - 1) * q
    const lower = Math.floor(position)
    const upper = Math.ceil(position)
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower)
}

function summarizeSorted(sorted: readonly number[]): ViolinSummary {
    let sum = 0
    for (const value of sorted) {
        sum += value
    }
    return {
        count: sorted.length,
        min: sorted[0],
        p25: quantileOfSorted(sorted, 0.25),
        median: quantileOfSorted(sorted, 0.5),
        mean: sum / sorted.length,
        p75: quantileOfSorted(sorted, 0.75),
        max: sorted[sorted.length - 1],
    }
}

function prepare(datum: ViolinPlotDatum, logScale: boolean): PreparedViolin | null {
    const cache = logScale ? logCache : linearCache
    if (cache.has(datum)) {
        return cache.get(datum) ?? null
    }
    const usable = datum.values.filter((value) => Number.isFinite(value) && (!logScale || value > 0))
    let prepared: PreparedViolin | null = null
    if (usable.length > 0) {
        const summary = summarizeSorted(usable.slice().sort((a, b) => a - b))
        const sorted = usable.map((value) => (logScale ? Math.log10(value) : value)).sort((a, b) => a - b)
        prepared = { sorted, summary }
    }
    cache.set(datum, prepared)
    return prepared
}

/** Summary statistics of a violin's finite observations, or `null` when it has none. On a log
 *  axis (`logScale`) values that are not positive are left out, exactly as the chart leaves them
 *  out when drawing, so the numbers match the median tick and mean marker on screen. */
export function summarizeViolin(datum: ViolinPlotDatum, logScale = false): ViolinSummary | null {
    return prepare(datum, logScale)?.summary ?? null
}

function thinEvenly<T>(values: readonly T[], limit: number): T[] {
    if (values.length <= limit) {
        return values.slice()
    }
    const out: T[] = []
    for (let i = 0; i < limit; i++) {
        out.push(values[Math.floor((i * (values.length - 1)) / (limit - 1))])
    }
    return out
}

/** Silverman's rule of thumb on the smaller of the standard deviation and the scaled
 *  interquartile range, so a few outliers do not widen the whole violin. */
function ruleOfThumbBandwidth(sorted: readonly number[]): number {
    const n = sorted.length
    const mean = sorted.reduce((total, value) => total + value, 0) / n
    const variance = n > 1 ? sorted.reduce((total, value) => total + (value - mean) ** 2, 0) / (n - 1) : 0
    const deviation = Math.sqrt(variance)
    const spread = quantileOfSorted(sorted, 0.75) - quantileOfSorted(sorted, 0.25)
    const scale = spread > 0 ? Math.min(deviation, spread / 1.34) : deviation
    return 0.9 * scale * n ** -0.2
}

export interface DensityPoint {
    value: number
    density: number
}

/** Gaussian kernel density of ascending `sorted` values, sampled evenly across `[lo, hi]`. Only the
 *  values within the kernel window of a sample contribute to it. */
export function densityProfile(
    sorted: readonly number[],
    lo: number,
    hi: number,
    bandwidth: number,
    samples: number = DENSITY_SAMPLES
): DensityPoint[] {
    const reach = KERNEL_REACH * bandwidth
    const out: DensityPoint[] = []
    let windowStart = 0
    for (let i = 0; i < samples; i++) {
        const value = samples === 1 ? lo : lo + ((hi - lo) * i) / (samples - 1)
        while (windowStart < sorted.length && sorted[windowStart] < value - reach) {
            windowStart++
        }
        let density = 0
        for (let j = windowStart; j < sorted.length && sorted[j] <= value + reach; j++) {
            density += Math.exp(-0.5 * ((value - sorted[j]) / bandwidth) ** 2)
        }
        out.push({ value, density })
    }
    return out
}

/** A stable offset in `[-0.5, 0.5)` for the observation at `index`. Deterministic, so the markers
 *  do not move between repaints. */
function jitterOf(index: number): number {
    return ((index * GOLDEN_RATIO_CONJUGATE) % 1) - 0.5
}

export interface ComputeViolinRectOptions {
    seriesKey: string
    label: string
    dataIndex: number
    datum: ViolinPlotDatum
    scales: BarScaleSet
    /** Whether the chart is in grouped mode (multiple series → side-by-side violins within a band). */
    grouped: boolean
    /** The value axis is logarithmic: the density is estimated on log10 of the values. */
    logScale?: boolean
    showPoints: boolean
}

/** Single-violin geometry. Pure: takes already-built scales and returns pixel coordinates only.
 *  Returns `null` when the slot cannot be resolved or the datum has no usable values. */
export function computeViolinRect({
    seriesKey,
    label,
    dataIndex,
    datum,
    scales,
    grouped,
    logScale = false,
    showPoints,
}: ComputeViolinRectOptions): ViolinRect | null {
    const slot = computeBandSlot(seriesKey, label, scales, grouped)
    const prepared = prepare(datum, logScale)
    if (!slot || !prepared) {
        return null
    }
    const { sorted, summary } = prepared
    const centerX = slot.x + slot.width / 2

    const [domainStart, domainEnd] = scales.value.domain()
    const toSpace = (value: number): number => (logScale ? Math.log10(Math.max(value, Number.MIN_VALUE)) : value)
    const fromSpace = (value: number): number => (logScale ? 10 ** value : value)
    const spaceLo = Math.min(toSpace(domainStart), toSpace(domainEnd))
    const spaceHi = Math.max(toSpace(domainStart), toSpace(domainEnd))

    const densitySource = thinEvenly(sorted, MAX_DENSITY_VALUES)
    const bandwidth = Math.max(
        ruleOfThumbBandwidth(densitySource),
        (spaceHi - spaceLo) * MIN_BANDWIDTH_RATIO,
        Number.EPSILON
    )
    const outlineLo = Math.max(spaceLo, densitySource[0] - TAIL_BANDWIDTHS * bandwidth)
    const outlineHi = Math.min(spaceHi, densitySource[densitySource.length - 1] + TAIL_BANDWIDTHS * bandwidth)
    const profile = densityProfile(densitySource, outlineLo, outlineHi, bandwidth)
    const peak = profile.reduce((widest, point) => Math.max(widest, point.density), 0)
    if (!(peak > 0) || outlineHi <= outlineLo) {
        return null
    }

    const halfWidthAtPeak = (slot.width / 2) * VIOLIN_WIDTH_RATIO
    const outline = profile.map((point) => ({
        y: scales.value(fromSpace(point.value)),
        halfWidth: (point.density / peak) * halfWidthAtPeak,
    }))
    const medianY = scales.value(summary.median)
    const meanY = scales.value(summary.mean)
    if (!Number.isFinite(medianY) || !Number.isFinite(meanY) || outline.some((point) => !Number.isFinite(point.y))) {
        return null
    }

    const points: ViolinRect['points'] = []
    if (showPoints) {
        const markers = thinEvenly(sorted, MAX_DRAWN_POINTS)
        for (const [index, marker] of markers.entries()) {
            const y = scales.value(fromSpace(marker))
            if (Number.isFinite(y)) {
                points.push({ x: centerX + jitterOf(index) * slot.width * POINT_SPREAD_RATIO, y })
            }
        }
    }

    return {
        x: slot.x,
        width: slot.width,
        centerX,
        outline,
        medianY,
        mean: { x: centerX, y: meanY },
        points,
        dataIndex,
    }
}

export interface ComputeSeriesViolinsOptions {
    seriesKey: string
    data: (ViolinPlotDatum | null)[]
    labels: string[]
    scales: BarScaleSet
    grouped: boolean
    logScale?: boolean
    showPoints: boolean
}

/** Lays out every renderable violin for one series. Skipped indices (`null` datum or an
 *  unresolvable slot) are dropped — the caller can join back to `data` via `ViolinRect.dataIndex`. */
export function computeSeriesViolins({
    seriesKey,
    data,
    labels,
    scales,
    grouped,
    logScale,
    showPoints,
}: ComputeSeriesViolinsOptions): ViolinRect[] {
    const out: ViolinRect[] = []
    const length = Math.min(data.length, labels.length)
    for (let i = 0; i < length; i++) {
        const datum = data[i]
        if (!datum) {
            continue
        }
        const rect = computeViolinRect({
            seriesKey,
            label: labels[i],
            dataIndex: i,
            datum,
            scales,
            grouped,
            logScale,
            showPoints,
        })
        if (rect) {
            out.push(rect)
        }
    }
    return out
}
