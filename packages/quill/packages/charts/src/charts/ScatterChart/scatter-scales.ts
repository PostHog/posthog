import { scaleLinear, scaleLog } from 'd3-scale'

import { X_LABEL_EDGE_PADDING } from '../../core/hooks/useChartMargins'
import { autoFormatterFor, buildValueScale, sanitizeFixedDomain } from '../../core/scales'
import type { D3YScale } from '../../core/scales'
import { computeVisibleValueTicks } from '../../overlays/AxisLabels'
import { measureLabelWidth } from '../../utils/text-measure'
import { scatterValueRange } from './scatter-data'
import type { FlatScatterPoint } from './scatter-data'
import type { ScatterAxisConfig } from './types'

// Wider than the y axis' spacing because horizontal numeric labels are wide.
const X_TICK_SPACING_PX = 90
const MAX_X_TICKS = 12

export interface ScatterXTick {
    tick: number
    text: string
    x: number
}

export type ScatterAxisScale = Pick<ScatterAxisConfig, 'scaleType' | 'domain' | 'startAtZero'>

export function xTickCountForWidth(plotWidth: number): number {
    if (!isFinite(plotWidth) || plotWidth <= 0) {
        return 2
    }
    return Math.max(2, Math.min(MAX_X_TICKS, Math.floor(plotWidth / X_TICK_SPACING_PX)))
}

/** Derived through the shared value-scale builder when unpinned, so a scatter axis gets the same log,
 *  degenerate-range, and `nice()` handling as every other value axis. */
export function buildScatterAxisScale(
    points: FlatScatterPoint[],
    axis: 'x' | 'y',
    pixelRange: [number, number],
    tickCount: number,
    { scaleType = 'linear', domain, startAtZero = false }: ScatterAxisScale
): D3YScale {
    if (domain) {
        const [min, max] = sanitizeFixedDomain(domain)
        // A log scale maps a non-positive bound to NaN, blanking the plot, so fall back to linear.
        if (scaleType === 'log' && min > 0) {
            return scaleLog().domain([min, max]).range(pixelRange).clamp(true)
        }
        return scaleLinear().domain([min, max]).range(pixelRange)
    }
    return buildValueScale({
        range: scatterValueRange(points, axis),
        valueRange: pixelRange,
        tickCount,
        scaleType,
        floatBaseline: !startAtZero,
    })
}

/** Thinned by label collision, since a grid line under no label reads as a stray. */
export function resolveXTicks(
    xScale: D3YScale,
    tickCount: number,
    tickFormatter: ((value: number) => string) | undefined
): ScatterXTick[] {
    const ticks = xScale.ticks?.(tickCount) ?? []
    return computeVisibleValueTicks(ticks, xScale, tickFormatter ?? autoFormatterFor(ticks))
}

// A y range runs bottom-to-top and a domain may descend, so neither end is reliably the low one.
function bounds(interval: number[]): [number, number] {
    const first = interval[0]
    const last = interval[interval.length - 1]
    return first <= last ? [first, last] : [last, first]
}

export function domainBounds(scale: D3YScale): [number, number] {
    return bounds(scale.domain())
}

/** A drag can end outside the plot, where inverting the raw pixel reports a value the user never
 *  brushed. A log scale clamps on `invert` already; this makes the linear one agree. */
export function clampToRange(pixel: number, scale: D3YScale): number {
    const [low, high] = bounds(scale.range())
    return Math.min(Math.max(pixel, low), high)
}

/** Gutter for the outer half of a tick label centered on the plot's edge, which `overflow` would
 *  otherwise cut. An estimate, since the ticks that render depend on the plot width this decides. */
export function xLabelEdgeReserve(
    points: FlatScatterPoint[],
    domain: readonly [number, number] | undefined,
    tickFormatter: ((value: number) => string) | undefined
): number {
    let extent: [number, number]
    if (domain) {
        extent = sanitizeFixedDomain(domain)
    } else {
        const range = scatterValueRange(points, 'x')
        if (range.count === 0) {
            return 0
        }
        extent = [range.min, range.max]
    }
    const ticks = scaleLinear().domain(extent).nice(6).ticks(6)
    const format = tickFormatter ?? autoFormatterFor(ticks)
    let widest = 0
    for (const tick of ticks) {
        widest = Math.max(widest, measureLabelWidth(format(tick)))
    }
    return Math.ceil(widest / 2) + X_LABEL_EDGE_PADDING
}
