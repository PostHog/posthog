import { scaleBand, scaleLinear, scaleLog, type ScaleBand, type ScaleLinear, type ScaleLogarithmic } from 'd3-scale'

import {
    groupVisibleSeriesByAxis,
    niceLogDomain,
    orderedAxisPositions,
    seriesValueRange,
    type StackedBand,
    yTickCountForHeight,
} from './scales'
import type { ChartDimensions, Series, SeriesType } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

type D3YScale = ScaleLinear<number, number> | ScaleLogarithmic<number, number>

/** Combo chart scale set — a band x-axis plus per-axis value scales spanning every series on
 *  that axis. `yAxes` is always populated (even for single-axis charts) so combo draw code has
 *  one lookup path. `group` is the sub-band for grouped bar layout, built from bar-series keys
 *  only — lines/areas don't participate.
 *
 *  `value` aliases the primary axis scale so the set is structurally a `BarScaleSet` and can be
 *  passed straight into the shared bar helpers (`computeBarAtIndex`, `bandCenter`, `resolveBarsAtCursor`). */
export interface ComboScaleSet {
    band: ScaleBand<string>
    yAxes: Record<string, { scale: D3YScale; position: 'left' | 'right' }>
    /** Primary (default/left) axis value scale. */
    y: D3YScale
    /** Alias of `y` — present so this set satisfies `BarScaleSet` for the shared bar helpers. */
    value: D3YScale
    group?: ScaleBand<string>
}

/** Brand for the ComboChart `ChartScales._private` slot. Single source of truth so a shape
 *  change in `ComboScaleSet` doesn't drift between consumers. */
export interface ComboChartPrivate {
    __comboChart: ComboScaleSet
}

export interface CreateComboScalesOptions {
    scaleType?: 'linear' | 'log'
    barLayout?: 'stacked' | 'grouped'
    bandPadding?: number
    groupPadding?: number
    seriesTypeOf: (series: Series) => SeriesType
    /** Stacked-band data for bar series. Required when `barLayout` is `'stacked'`. */
    barStackedData?: Map<string, StackedBand>
}

export function resolveSeriesType(series: Pick<Series, 'type'>, defaultType: SeriesType): SeriesType {
    return series.type ?? defaultType
}

export function isLineLike(type: SeriesType): boolean {
    return type === 'line' || type === 'area'
}

/** Resolve the value scale for a series against its axis, falling back to the primary scale. */
export function resolveComboYScale(scales: ComboScaleSet, series: Pick<Series, 'yAxisId'>): D3YScale {
    return scales.yAxes[series.yAxisId ?? DEFAULT_Y_AXIS_ID]?.scale ?? scales.y
}

export function createComboScales(
    series: Series[],
    labels: string[],
    dimensions: ChartDimensions,
    options: CreateComboScalesOptions
): ComboScaleSet {
    const {
        scaleType = 'linear',
        barLayout = 'stacked',
        bandPadding = 0.2,
        groupPadding = 0.1,
        seriesTypeOf,
        barStackedData,
    } = options

    const band = scaleBand<string>()
        .domain(labels)
        .range([dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth])
        .paddingInner(bandPadding)
        .paddingOuter(bandPadding / 2)

    // Sub-band restricted to bar series — lines/areas plot at band centers regardless of
    // grouped-bar offsets, so they do not contribute keys here.
    let group: ScaleBand<string> | undefined
    if (barLayout === 'grouped') {
        const barKeys = series.filter((s) => !s.visibility?.excluded && seriesTypeOf(s) === 'bar').map((s) => s.key)
        group = scaleBand<string>().domain(barKeys).range([0, band.bandwidth()]).padding(groupPadding)
    }

    const tickCount = yTickCountForHeight(dimensions.plotHeight)
    const valueRange: [number, number] = [dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop]

    // Empty chart still needs an axis to draw against.
    const axisPositions = orderedAxisPositions(series)
    if (axisPositions.length === 0) {
        axisPositions.push({ axisId: DEFAULT_Y_AXIS_ID, position: 'left' })
    }
    const seriesByAxis = groupVisibleSeriesByAxis(series)
    const yAxes: ComboScaleSet['yAxes'] = {}
    for (const { axisId, position } of axisPositions) {
        const axisSeries = seriesByAxis.get(axisId) ?? []
        // Per-axis contributions: bars contribute their stacked-top values when stacked, raw
        // otherwise; lines/areas always contribute raw. The value scale spans the union.
        const contributing: Series[] = axisSeries.map((s) => {
            const stacked = barStackedData?.get(s.key)
            if (seriesTypeOf(s) === 'bar' && barLayout === 'stacked' && stacked) {
                return { ...s, data: stacked.top }
            }
            return s
        })
        yAxes[axisId] = { scale: buildComboValueScale(contributing, valueRange, tickCount, scaleType), position }
    }

    const primaryAxisId = axisPositions.some((a) => a.axisId === DEFAULT_Y_AXIS_ID)
        ? DEFAULT_Y_AXIS_ID
        : axisPositions[0].axisId
    const primary = yAxes[primaryAxisId].scale

    return { band, group, yAxes, y: primary, value: primary }
}

function buildComboValueScale(
    series: Series[],
    valueRange: [number, number],
    tickCount: number,
    scaleType: 'linear' | 'log'
): D3YScale {
    const range = seriesValueRange(series)
    if (range.count === 0) {
        return scaleLinear().domain([0, 1]).range(valueRange)
    }
    let { min, max } = range
    if (scaleType === 'log' && isFinite(range.minPositive)) {
        return scaleLog().domain(niceLogDomain(range.minPositive, max)).range(valueRange).clamp(true)
    }
    // Auxiliary overlays (trendline projections, moving averages) may dip below 0 when the
    // underlying data does not. They shouldn't drag the axis baseline below 0 — d3.nice()
    // applied to a slightly-negative min produces a disproportionately large negative tick
    // (e.g. [-1, 14500] → [-2000, 16000]). Mirrors the `createYScale` baseline logic.
    const primaryRange = series.some((s) => s.overlay) ? seriesValueRange(series.filter((s) => !s.overlay)) : range
    if (primaryRange.count > 0 && primaryRange.min >= 0) {
        min = 0
    } else if (max < 0) {
        max = 0
    }
    return scaleLinear().domain([min, max]).nice(tickCount).range(valueRange)
}

/** Partition visible series into bar vs line/area buckets, preserving input order within each
 *  bucket. Excluded series are dropped. */
export function partitionByType<S extends Pick<Series, 'visibility'>>(
    series: readonly S[],
    typeOf: (s: S) => SeriesType
): { bars: S[]; lines: S[] } {
    const bars: S[] = []
    const lines: S[] = []
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        if (typeOf(s) === 'bar') {
            bars.push(s)
        } else {
            lines.push(s)
        }
    }
    return { bars, lines }
}
