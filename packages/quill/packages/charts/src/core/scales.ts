import {
    scaleBand,
    scaleLinear,
    scaleLog,
    scalePoint,
    type ScaleBand,
    type ScaleLinear,
    type ScaleLogarithmic,
    type ScalePoint,
} from 'd3-scale'
import { stack as stackGen, stackOffsetDiverging, stackOffsetExpand, stackOffsetNone } from 'd3-shape'

import type { BandSlot, ChartDimensions, ResolveValueFn, Series, ValueDomain, YAxisScale } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

/** Inner padding fraction applied to the band scale when `BarChartConfig.bars.bandPadding` is unset. */
export const DEFAULT_BAND_PADDING = 0.2

export type D3YScale = ScaleLinear<number, number> | ScaleLogarithmic<number, number>

export interface ScaleSet {
    x: ScalePoint<string>
    y: D3YScale
    /** Per-axis d3 scales keyed by axis id. Only populated when multiple axes are present. */
    yAxes?: Record<string, { scale: D3YScale; position: 'left' | 'right' }>
}

export interface SeriesValueRange {
    /** Smallest finite value across all visible series, or `Infinity` if none. */
    min: number
    /** Largest finite value across all visible series, or `-Infinity` if none. */
    max: number
    /** Smallest strictly-positive finite value, or `Infinity` if none. Used by log scales. */
    minPositive: number
    /** Number of finite values seen. `0` means the result is empty — `min`/`max` are sentinel. */
    count: number
}

/**
 * Single-pass min/max over visible series, skipping excluded series and
 * non-finite values. Equivalent to `d3.min`/`d3.max` over a flatMap+filter
 * but avoids the intermediate arrays — the spread form (`Math.min(...arr)`)
 * also overflows the call stack at ~100k+ values.
 */
export function seriesValueRange(series: Series[]): SeriesValueRange {
    let min = Infinity
    let max = -Infinity
    let minPositive = Infinity
    let count = 0
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        // A confidence ribbon's lower bound (`fill.lowerData`) is part of the data's visible
        // extent, so it must widen the axis too — otherwise the band clips at the top series.
        for (const v of s.fill?.lowerData ? [...s.data, ...s.fill.lowerData] : s.data) {
            if (v == null || !isFinite(v)) {
                continue
            }
            count++
            if (v < min) {
                min = v
            }
            if (v > max) {
                max = v
            }
            if (v > 0 && v < minPositive) {
                minPositive = v
            }
        }
    }
    return { min, max, minPositive, count }
}

/** Split a {@link ValueDomain} into its two mutually-exclusive modes — a fixed `[min, max]`
 *  or the set of values an auto-scaled domain must `include`. */
function resolveValueDomain(valueDomain: ValueDomain | undefined): {
    fixed?: readonly [number, number]
    include?: readonly number[]
} {
    if (!valueDomain) {
        return {}
    }
    if ('include' in valueDomain) {
        return { include: valueDomain.include }
    }
    return { fixed: valueDomain }
}

/** Fold extra values (e.g. goal-line targets) into a range so the axis covers them even when
 *  they sit outside the data's natural extent. */
export function extendValueRange(range: SeriesValueRange, values: readonly number[]): SeriesValueRange {
    let { min, max, minPositive, count } = range
    for (const v of values) {
        if (v == null || !isFinite(v)) {
            continue
        }
        count++
        if (v < min) {
            min = v
        }
        if (v > max) {
            max = v
        }
        if (v > 0 && v < minPositive) {
            minPositive = v
        }
    }
    return { min, max, minPositive, count }
}

/** Round `minPositive` down to the previous decade, `max` up to the next round multiple
 *  of its top decade (e.g. 740 → 800, 4200 → 5000). */
export function niceLogDomain(minPositive: number, max: number): [number, number] {
    const niceMin = Math.pow(10, Math.ceil(Math.log10(minPositive)) - 1)
    const maxDecade = Math.pow(10, Math.floor(Math.log10(max)))
    const niceMax = Math.ceil(max / maxDecade) * maxDecade
    return [niceMin, niceMax]
}

export function createXScale(labels: string[], dimensions: ChartDimensions): ScalePoint<string> {
    return scalePoint<string>()
        .domain(labels)
        .range([dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth])
        .padding(0)
}

export function yTickCountForHeight(plotHeight: number): number {
    return Math.max(2, Math.min(11, Math.floor(plotHeight / 50)))
}

export function createYScale(
    series: Series[],
    dimensions: ChartDimensions,
    options: {
        scaleType?: 'linear' | 'log'
        percentStack?: boolean
        /** Fixed `[min, max]` or `{ include }` extra values the domain must cover. */
        valueDomain?: ValueDomain
        /** Float the axis to its data range instead of clamping the baseline to 0. See {@link buildValueScale}. */
        floatBaseline?: boolean
    } = {}
): ScaleLinear<number, number> | ScaleLogarithmic<number, number> {
    const { scaleType = 'linear', percentStack = false, valueDomain, floatBaseline = false } = options
    const { fixed, include } = resolveValueDomain(valueDomain)
    const tickCount = yTickCountForHeight(dimensions.plotHeight)

    if (fixed) {
        return scaleLinear()
            .domain([fixed[0], fixed[1]])
            .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])
    }

    if (percentStack) {
        return scaleLinear()
            .domain([0, 1])
            .nice(tickCount)
            .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])
    }

    const dataRange = seriesValueRange(series)
    const range = include?.length ? extendValueRange(dataRange, include) : dataRange

    // A negative `include` value (a goal line below 0) is explicit, so it must not be clamped away.
    const hasExplicitNegativeGoal = include?.some((v) => v != null && isFinite(v) && v < 0) ?? false
    const primaryRange = series.some((s) => s.overlay) ? seriesValueRange(series.filter((s) => !s.overlay)) : dataRange

    return buildValueScale({
        range,
        primaryRange,
        valueRange: [dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop],
        tickCount,
        scaleType,
        allowNegativeBaseline: hasExplicitNegativeGoal,
        floatBaseline,
    })
}

/** Build a value (y, or x for horizontal) scale from a precomputed {@link SeriesValueRange}, applying
 *  the overlay-aware zero-baseline clamp, the degenerate `min === max` guard, and the log/no-positive
 *  fallback. Single source of truth shared by `createYScale` and the combo chart's per-axis scales so
 *  the baseline logic can't drift between them. */
export function buildValueScale(options: {
    range: SeriesValueRange
    /** Pixel range `[lowEdge, highEdge]` — for a vertical y-scale this is `[bottom, top]`. */
    valueRange: [number, number]
    tickCount: number
    scaleType?: 'linear' | 'log'
    /** Range used for the overlay-aware zero-baseline clamp; defaults to `range`. Overlays
     *  (trendlines, moving averages) may dip below 0 when the underlying data doesn't — they
     *  shouldn't drag the baseline negative, since `d3.nice()` on a slightly-negative min yields a
     *  disproportionately large negative tick (e.g. [-1, 14500] → [-2000, 16000]). */
    primaryRange?: SeriesValueRange
    /** Keep a negative min even when the primary data is non-negative (an explicit negative goal). */
    allowNegativeBaseline?: boolean
    /** Skip the zero-baseline clamp entirely so the axis floats to its data range (a y-axis "start at
     *  zero = off"). The default clamps a non-negative axis down to 0. Has no effect on a log scale. */
    floatBaseline?: boolean
}): D3YScale {
    const {
        range,
        valueRange,
        tickCount,
        scaleType = 'linear',
        primaryRange = range,
        allowNegativeBaseline = false,
        floatBaseline = false,
    } = options

    if (range.count === 0) {
        return scaleLinear().domain([0, 1]).range(valueRange)
    }

    let { min, max } = range

    if (scaleType === 'log') {
        if (!isFinite(range.minPositive)) {
            // No positive values for a log scale (e.g. all-zero data). Fall back to linear, and
            // bracket a degenerate `min === max` domain so it doesn't collapse to NaN.
            let logMin = min
            let logMax = max
            if (logMin === logMax) {
                logMin = Math.min(0, logMin)
                logMax = Math.max(0, logMax, logMin + 1)
            }
            return scaleLinear().domain([logMin, logMax]).nice(tickCount).range(valueRange)
        }
        return scaleLog().domain(niceLogDomain(range.minPositive, max)).range(valueRange).clamp(true)
    }

    if (!floatBaseline) {
        if (primaryRange.count > 0 && primaryRange.min >= 0 && !allowNegativeBaseline) {
            min = 0
        } else if (max < 0) {
            max = 0
        }
    }

    // The range can collapse to a single point (e.g. all-equal data, or `include`-only goal values
    // like `[100, 100]`) — a degenerate domain that maps everything to NaN. Bracket zero, then
    // guarantee a unit span, so the axis stays well-formed.
    if (min === max) {
        min = Math.min(0, min)
        max = Math.max(0, max, min + 1)
    }

    return scaleLinear().domain([min, max]).nice(tickCount).range(valueRange)
}

/** Map raw d3 per-axis scales into the public {@link YAxisScale} shape (value→pixel fn + tick
 *  accessor + side). Shared by every multi-axis chart's `createScales` so the wrapping is uniform. */
export function toYAxisScales(
    d3Axes: Record<string, { scale: D3YScale; position: 'left' | 'right' }>,
    tickCount: number
): Record<string, YAxisScale> {
    const yAxes: Record<string, YAxisScale> = {}
    for (const [axisId, { scale, position }] of Object.entries(d3Axes)) {
        yAxes[axisId] = {
            scale: (value: number) => scale(value),
            ticks: () => scale.ticks?.(tickCount) ?? [],
            position,
        }
    }
    return yAxes
}

/** Topmost visible series key per axis id — the cap-rounded layer of each stack. Iteration order
 *  matches d3.stack's key order, so the last write per axis is that axis's top layer. `skip` lets a
 *  mixed-type chart exclude non-bar series so only bars determine the cap. */
export function computeTopStackedKeyByAxis<S extends Pick<Series, 'key' | 'visibility' | 'yAxisId'>>(
    series: readonly S[],
    options: { skip?: (s: S) => boolean } = {}
): Map<string, string> {
    const m = new Map<string, string>()
    for (const s of series) {
        if (s.visibility?.excluded || options.skip?.(s)) {
            continue
        }
        m.set(s.yAxisId ?? DEFAULT_Y_AXIS_ID, s.key)
    }
    return m
}

/** Order the visible series' axis ids — DEFAULT_Y_AXIS_ID first (when present), then the
 *  remaining ids in first-encountered order — and assign alternating positions starting on the
 *  left: index 0 left, 1 right, 2 left, 3 right, … Each side stacks its gutters outward in this
 *  order. Mirrors the legacy multi-axis trends rendering and is shared by the scale builders and
 *  the margin/axis-label layout so they agree on how many gutters sit on each side. */
export function orderedAxisPositions(series: Series[]): { axisId: string; position: 'left' | 'right' }[] {
    const axisIds = new Set(series.filter((s) => !s.visibility?.excluded).map((s) => s.yAxisId ?? DEFAULT_Y_AXIS_ID))
    const ordered = [
        ...(axisIds.has(DEFAULT_Y_AXIS_ID) ? [DEFAULT_Y_AXIS_ID] : []),
        ...Array.from(axisIds).filter((id) => id !== DEFAULT_Y_AXIS_ID),
    ]
    return ordered.map((axisId, i) => ({ axisId, position: i % 2 === 0 ? 'left' : 'right' }))
}

/** Bucket visible series by axis id in a single O(series) pass so per-axis scale builders look
 *  their series up instead of re-filtering the whole list per axis (which is O(series²) when each
 *  series has its own axis, as in `showMultipleYAxes`). */
export function groupVisibleSeriesByAxis(series: Series[]): Map<string, Series[]> {
    const byAxis = new Map<string, Series[]>()
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        const id = s.yAxisId ?? DEFAULT_Y_AXIS_ID
        const bucket = byAxis.get(id)
        if (bucket) {
            bucket.push(s)
        } else {
            byAxis.set(id, [s])
        }
    }
    return byAxis
}

export function createScales(
    series: Series[],
    labels: string[],
    dimensions: ChartDimensions,
    options: {
        scaleType?: 'linear' | 'log'
        percentStack?: boolean
        /** Applied to the primary y-axis only — goal lines (`{ include }`) render against the
         *  primary axis, so secondary axes keep their own data-derived scale. */
        valueDomain?: ValueDomain
        /** Per-axis overrides keyed by axis id. When an axis is listed its `scaleType` and
         *  `position` win; otherwise it falls back to `options.scaleType` and the alternating-side
         *  default from {@link orderedAxisPositions}. */
        axes?: { id: string; position?: 'left' | 'right'; scaleType?: 'linear' | 'log' }[]
        /** Float the primary axis to its data range instead of clamping the baseline to 0. Applied to
         *  the primary axis only, like `valueDomain`. See {@link buildValueScale}. */
        floatBaseline?: boolean
    } = {}
): ScaleSet {
    const x = createXScale(labels, dimensions)

    const positions = orderedAxisPositions(series)
    const axisOverrides = new Map((options.axes ?? []).map((a) => [a.id, a]))

    // A sole axis explicitly positioned right must still produce a `yAxes` record — otherwise the
    // scalar fast path below emits no per-axis info and the gutter always renders on the left.
    const soleAxisId = positions[0]?.axisId ?? DEFAULT_Y_AXIS_ID
    const soleAxisOnRight = positions.length === 1 && axisOverrides.get(soleAxisId)?.position === 'right'
    const hasMultipleAxes = positions.length > 1

    if (!hasMultipleAxes && !soleAxisOnRight) {
        const y = createYScale(series, dimensions, {
            scaleType: axisOverrides.get(soleAxisId)?.scaleType ?? options.scaleType,
            percentStack: options.percentStack,
            valueDomain: options.valueDomain,
            floatBaseline: options.floatBaseline,
        })
        return { x, y }
    }

    const byAxis = groupVisibleSeriesByAxis(series)
    const yAxes: Record<string, { scale: D3YScale; position: 'left' | 'right' }> = {}
    positions.forEach(({ axisId, position }, axisIndex) => {
        const override = axisOverrides.get(axisId)
        const scale = createYScale(byAxis.get(axisId) ?? [], dimensions, {
            scaleType: override?.scaleType ?? options.scaleType,
            percentStack: options.percentStack,
            valueDomain: axisIndex === 0 ? options.valueDomain : undefined,
            floatBaseline: axisIndex === 0 ? options.floatBaseline : undefined,
        })
        yAxes[axisId] = { scale, position: override?.position ?? position }
    })

    const primaryAxis = yAxes[DEFAULT_Y_AXIS_ID] ?? yAxes[positions[0].axisId]

    return { x, y: primaryAxis.scale, yAxes }
}

export interface StackedBand {
    top: number[]
    bottom: number[]
}

function buildStackData(
    series: Series[],
    labels: string[],
    options: { offset?: typeof stackOffsetNone; allowNegative?: boolean } = {}
): Map<string, StackedBand> {
    const { offset, allowNegative = false } = options
    const visibleSeries = series.filter((s) => !s.visibility?.excluded && !s.fill?.lowerData && !s.overlay)
    if (visibleSeries.length === 0) {
        return new Map()
    }

    const result = new Map<string, StackedBand>()

    const seriesByAxis = new Map<string, Series[]>()
    for (const s of visibleSeries) {
        const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
        const bucket = seriesByAxis.get(axisId)
        if (bucket) {
            bucket.push(s)
        } else {
            seriesByAxis.set(axisId, [s])
        }
    }

    for (const axisSeries of seriesByAxis.values()) {
        const tableData = labels.map((_, i) => {
            const row: Record<string, number> = {}
            for (const s of axisSeries) {
                const raw = s.data[i] ?? 0
                row[s.key] = allowNegative ? raw : Math.max(0, raw)
            }
            return row
        })

        const stack = stackGen<Record<string, number>>().keys(axisSeries.map((s) => s.key))
        if (offset) {
            stack.offset(offset)
        }

        const stacked = stack(tableData)
        for (const layer of stacked) {
            // stackOffsetExpand emits NaN for all-zero columns; flatten so consumers don't have to guard.
            result.set(layer.key, {
                top: layer.map((d) => (Number.isFinite(d[1]) ? d[1] : 0)),
                bottom: layer.map((d) => (Number.isFinite(d[0]) ? d[0] : 0)),
            })
        }
    }

    return result
}

export function computeStackData(series: Series[], labels: string[]): Map<string, StackedBand> {
    return buildStackData(series, labels)
}

export function computePercentStackData(series: Series[], labels: string[]): Map<string, StackedBand> {
    return buildStackData(series, labels, { offset: stackOffsetExpand })
}

/** Stack that preserves negative segments — positives accumulate upward from 0, negatives
 *  downward from 0 (stackOffsetDiverging). Used by Lifecycle, where `dormant` is emitted
 *  as a negative series so it renders below the zero baseline. */
export function computeDivergingStackData(series: Series[], labels: string[]): Map<string, StackedBand> {
    return buildStackData(series, labels, { offset: stackOffsetDiverging, allowNegative: true })
}

/** Returns the stacked top of each series so the tooltip anchor and value-label position
 *  land at the visual top of each segment. This is a *position* resolver — for the value
 *  to *display* (the segment, not the cumulative total) use {@link buildSegmentResolveValue}.
 *  Falls back to the raw value when the series isn't part of the stack (e.g. trend-line
 *  overlays, CI bands). */
export function buildStackedPositionValue(
    stackedData: Map<string, StackedBand> | undefined
): ResolveValueFn | undefined {
    if (!stackedData) {
        return undefined
    }
    return (s, dataIndex) => {
        const stacked = stackedData.get(s.key)?.top[dataIndex]
        if (stacked != null && Number.isFinite(stacked)) {
            return stacked
        }
        const raw = s.data[dataIndex]
        return typeof raw === 'number' && Number.isFinite(raw) ? raw : 0
    }
}

/** Returns each series's own segment height (`top − bottom`) — the per-series value to
 *  display, not the cumulative stack total. Falls back to the raw value for series not in
 *  the stack. Pair with {@link buildStackedPositionValue} for anchor positioning. */
export function buildSegmentResolveValue(
    stackedData: Map<string, StackedBand> | undefined
): ResolveValueFn | undefined {
    if (!stackedData) {
        return undefined
    }
    return (s, dataIndex) => {
        const band = stackedData.get(s.key)
        if (band) {
            const top = band.top[dataIndex]
            const bottom = band.bottom[dataIndex]
            if (Number.isFinite(top) && Number.isFinite(bottom)) {
                return top - bottom
            }
        }
        const raw = s.data[dataIndex]
        return typeof raw === 'number' && Number.isFinite(raw) ? raw : 0
    }
}

/** Returns the stacked bottom value for each series — use with {@link buildStackedPositionValue}
 *  to compute per-segment midpoints for tooltip hover detection. */
export function buildStackedBottomValue(stackedData: Map<string, StackedBand> | undefined): ResolveValueFn | undefined {
    if (!stackedData) {
        return undefined
    }
    return (s, dataIndex) => {
        const bottom = stackedData.get(s.key)?.bottom[dataIndex]
        if (Number.isFinite(bottom)) {
            return bottom as number
        }
        // Non-stacked series (e.g. overlay trend lines) aren't in the stack map.
        // Fall back to the series value so the midpoint collapses to the series's
        // own pixel position — matching buildStackedPositionValue's fallback.
        const raw = s.data[dataIndex]
        return typeof raw === 'number' && Number.isFinite(raw) ? raw : 0
    }
}

export interface BarScaleSet {
    band: ScaleBand<string>
    value: D3YScale
    /** Sub-band for grouped layout — maps a series key to its offset inside a band. */
    group?: ScaleBand<string>
    /** Per-axis value scales keyed by axis id. Only populated for grouped layouts with
     *  more than one axis id across the visible series (`showMultipleYAxes`). `value` is
     *  the primary (left) axis scale. */
    yAxes?: Record<string, { scale: D3YScale; position: 'left' | 'right' }>
}

/** Band-axis slot of one series's bar within a grouped band: `{ x, width }` along the band axis.
 *  The single source of truth for grouped bar geometry — used for drawing, hit-testing, and
 *  tooltip anchoring. Returns undefined for non-grouped layouts or a series not in the group. */
export function groupedBandSlot(scales: BarScaleSet, label: string, seriesKey: string): BandSlot | undefined {
    const start = scales.band(label)
    const group = scales.group
    const offset = group?.(seriesKey)
    if (start == null || group == null || offset == null) {
        return undefined
    }
    return { x: start + offset, width: group.bandwidth() }
}

export function createBarScales(
    series: Series[],
    labels: string[],
    dimensions: ChartDimensions,
    options: {
        scaleType?: 'linear' | 'log'
        barLayout?: 'stacked' | 'grouped' | 'percent'
        axisOrientation?: 'vertical' | 'horizontal'
        bandPadding?: number
        groupPadding?: number
        stackedSeries?: Series[]
        /** Cap on the band-axis range in px — clusters bars at the start of the plot when set. */
        maxBandRange?: number
        /** Horizontal fit-to-height mode: drop the rows that can't fit at `minBandSize` so bands
         *  never crush below it and the plot fills the height it's given. Requires `minBandSize`. */
        fitToHeight?: boolean
        /** Minimum px per row — only consulted to compute the `fitToHeight` row cap. */
        minBandSize?: number
        /** Fixed `[min, max]` or `{ include }` extra values the value axis must cover. */
        valueDomain?: ValueDomain
        /** Px reserved past the bars at the value-axis data end(s) — see {@link BarsConfig.valuePadding}. */
        valuePadding?: number
        /** Per-axis overrides — explicit values win over the alternating-side default and `options.scaleType`. */
        axes?: { id: string; position?: 'left' | 'right'; scaleType?: 'linear' | 'log' }[]
    } = {}
): BarScaleSet {
    const {
        scaleType = 'linear',
        barLayout = 'stacked',
        axisOrientation = 'vertical',
        bandPadding = DEFAULT_BAND_PADDING,
        groupPadding = 0.1,
        stackedSeries,
        maxBandRange,
        fitToHeight,
        minBandSize,
        valueDomain,
        valuePadding = 0,
        axes,
    } = options

    const isHorizontal = axisOrientation === 'horizontal'
    const tickCount = yTickCountForHeight(isHorizontal ? dimensions.plotWidth : dimensions.plotHeight)

    const bandAxisStart = isHorizontal ? dimensions.plotTop : dimensions.plotLeft
    const bandAxisExtent = isHorizontal ? dimensions.plotHeight : dimensions.plotWidth
    const cappedExtent = maxBandRange != null ? Math.min(bandAxisExtent, maxBandRange) : bandAxisExtent
    // Fit-to-height: only keep the rows that fit at `minBandSize`. Labels arrive value-sorted, so
    // slicing keeps the leading rows. Bars/labels/grid all resolve through `band(label)`, so a
    // dropped label resolves to `undefined` and is skipped everywhere — no extra plumbing needed.
    let domainLabels = labels
    if (isHorizontal && fitToHeight && minBandSize && minBandSize > 0) {
        const maxBands = Math.max(1, Math.floor(cappedExtent / minBandSize))
        if (labels.length > maxBands) {
            domainLabels = labels.slice(0, maxBands)
        }
    }
    const band = scaleBand<string>()
        .domain(domainLabels)
        .range([bandAxisStart, bandAxisStart + cappedExtent])
        .paddingInner(bandPadding)
        .paddingOuter(bandPadding / 2)

    let group: ScaleBand<string> | undefined
    if (barLayout === 'grouped') {
        const visibleKeys = series.filter((s) => !s.visibility?.excluded).map((s) => s.key)
        group = scaleBand<string>().domain(visibleKeys).range([0, band.bandwidth()]).padding(groupPadding)
    }

    const valueRange: [number, number] = isHorizontal
        ? [dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth]
        : [dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop]

    // When fitToHeight drops rows, the value axis must scale to only the rendered bars — a dropped
    // off-screen bar (e.g. a dominant "Other" bucket) would otherwise stretch the domain and crush
    // every visible bar. domainLabels is a leading slice, so the kept rows are each series's first
    // `keptCount` data points.
    const keptCount = domainLabels.length
    const restrictToKept = (s: Series): Series =>
        keptCount < labels.length ? { ...s, data: s.data.slice(0, keptCount) } : s
    const valueSeries = series.map(restrictToKept)
    const valueStackedSeries = stackedSeries?.map(restrictToKept)

    // Per-axis scales for multi-axis charts (stacking is already per-axis). A sole axis pinned
    // right also needs a `yAxes` record — the fast path below always renders its gutter left.
    const visibleSeries = valueSeries.filter((s) => !s.visibility?.excluded)
    const axisOverrides = new Map((axes ?? []).map((a) => [a.id, a]))
    const positions = orderedAxisPositions(visibleSeries).map(({ axisId, position }) => ({
        axisId,
        position: axisOverrides.get(axisId)?.position ?? position,
    }))
    const soleAxisOnRight = positions.length === 1 && positions[0].position === 'right'
    if (positions.length > 1 || soleAxisOnRight) {
        const byAxis = groupVisibleSeriesByAxis(visibleSeries)
        const yAxes: Record<string, { scale: D3YScale; position: 'left' | 'right' }> = {}
        positions.forEach(({ axisId, position }, axisIndex) => {
            const axisSeries = byAxis.get(axisId) ?? []
            // Filter the pre-computed stacked tops to this axis, matching on yAxisId (not key) —
            // diverging stacks add synthetic `__bottom` entries whose yAxisId carries over.
            const axisStackedSeries = valueStackedSeries?.filter((s) => (s.yAxisId ?? DEFAULT_Y_AXIS_ID) === axisId)
            const scale = buildBarValueScale(
                axisSeries,
                valueRange,
                tickCount,
                barLayout,
                axisOverrides.get(axisId)?.scaleType ?? scaleType,
                axisStackedSeries?.length ? axisStackedSeries : undefined,
                axisIndex === 0 ? valueDomain : undefined,
                valuePadding
            )
            yAxes[axisId] = { scale, position }
        })
        const primary = yAxes[DEFAULT_Y_AXIS_ID] ?? yAxes[positions[0].axisId]
        return { band, value: primary.scale, group, yAxes }
    }

    return {
        band,
        value: buildBarValueScale(
            valueSeries,
            valueRange,
            tickCount,
            barLayout,
            scaleType,
            valueStackedSeries,
            valueDomain,
            valuePadding
        ),
        group,
    }
}

function buildBarValueScale(
    series: Series[],
    valueRange: [number, number],
    tickCount: number,
    barLayout: 'stacked' | 'grouped' | 'percent',
    scaleType: 'linear' | 'log',
    stackedSeries: Series[] | undefined,
    valueDomain: ValueDomain | undefined,
    valuePadding: number
): D3YScale {
    const { fixed, include } = resolveValueDomain(valueDomain)
    if (fixed) {
        return scaleLinear().domain([fixed[0], fixed[1]]).range(valueRange)
    }
    if (barLayout === 'percent') {
        return scaleLinear().domain([0, 1]).nice(tickCount).range(valueRange)
    }
    const range = include?.length
        ? extendValueRange(seriesValueRange(stackedSeries ?? series), include)
        : seriesValueRange(stackedSeries ?? series)
    if (range.count === 0) {
        return scaleLinear().domain([0, 1]).range(valueRange)
    }
    const min = range.min > 0 ? 0 : range.min
    let max = range.max < 0 ? 0 : range.max
    if (scaleType === 'log' && isFinite(range.minPositive)) {
        return scaleLog().domain(niceLogDomain(range.minPositive, max)).range(valueRange).clamp(true)
    }
    // Guard the degenerate single-point domain (e.g. empty data with a single goal value at 0).
    if (min === max) {
        max = min + 1
    }
    const scale = scaleLinear().domain([min, max]).nice(tickCount)
    return scale.range(padValueRange(valueRange, scale.domain() as [number, number], valuePadding))
}

// Hold back `paddingPx` of the value axis's pixel range at the data-extent end(s), so the bars stop
// short of the edge and an overlay (e.g. a value label) has room beyond the bar tip. Reserving range
// rather than extending the domain keeps the gap exactly `paddingPx` regardless of the data scale.
// Only the end(s) the bars actually reach are padded — the zero baseline stays pinned to the edge.
function padValueRange(
    [start, end]: [number, number],
    [min, max]: [number, number],
    paddingPx: number
): [number, number] {
    const span = Math.abs(end - start)
    if (paddingPx <= 0 || span === 0) {
        return [start, end]
    }
    // Cap each reserved end at a third of the axis so padding can't swallow the plot.
    const reserve = Math.min(paddingPx, span / 3) * Math.sign(start - end || 1)
    return [min < 0 ? start - reserve : start, max > 0 ? end + reserve : end]
}

export function autoFormatYTick(value: number, domainMax: number): string {
    if (domainMax < 2) {
        return value.toFixed(2)
    }
    if (domainMax < 5) {
        return value.toFixed(1)
    }
    return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

export function autoFormatterFor(ticks: number[]): (value: number) => string {
    const domainMax = ticks.length > 0 ? Math.max(...ticks.map((t) => Math.abs(t))) : 1
    return (v) => autoFormatYTick(v, domainMax)
}

export function resolveYScaleForSeries<S extends (value: number) => number>(
    scales: { y: S; yAxes?: Record<string, { scale: S }> },
    series: Pick<Series, 'yAxisId'>
): S {
    return scales.yAxes?.[series.yAxisId ?? DEFAULT_Y_AXIS_ID]?.scale ?? scales.y
}
