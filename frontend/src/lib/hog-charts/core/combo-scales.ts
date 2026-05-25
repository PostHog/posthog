import * as d3 from 'd3'

import { collectOrderedAxisIds, niceLogDomain, seriesValueRange, type StackedBand, yTickCountForHeight } from './scales'
import type { ChartDimensions, Series, SeriesType } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

type D3YScale = d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>

/** Combo chart scale set — band x-axis plus per-axis value scales spanning every series on
 *  that axis. `yAxes` is always populated (even for single-axis charts) so combo draw code
 *  has one lookup path. `group` is the sub-band for grouped bar layout, built from bar-series
 *  keys only — lines/areas don't participate. */
export interface ComboScaleSet {
    band: d3.ScaleBand<string>
    yAxes: Record<string, { scale: D3YScale; position: 'left' | 'right' }>
    y: D3YScale
    group?: d3.ScaleBand<string>
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

    const band = d3
        .scaleBand<string>()
        .domain(labels)
        .range([dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth])
        .paddingInner(bandPadding)
        .paddingOuter(bandPadding / 2)

    // Sub-band restricted to bar series — lines/areas plot at band centers regardless of
    // grouped-bar offsets, so they do not contribute keys here.
    let group: d3.ScaleBand<string> | undefined
    if (barLayout === 'grouped') {
        const barKeys = series.filter((s) => !s.visibility?.excluded && seriesTypeOf(s) === 'bar').map((s) => s.key)
        group = d3.scaleBand<string>().domain(barKeys).range([0, band.bandwidth()]).padding(groupPadding)
    }

    const tickCount = yTickCountForHeight(dimensions.plotHeight)
    const valueRange: [number, number] = [dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop]

    // Empty chart still needs an axis to draw against.
    const axisIds = collectOrderedAxisIds(series)
    if (axisIds.length === 0) {
        axisIds.push(DEFAULT_Y_AXIS_ID)
    }
    const yAxes: ComboScaleSet['yAxes'] = {}
    axisIds.forEach((axisId, axisIndex) => {
        const axisSeries = series.filter((s) => !s.visibility?.excluded && (s.yAxisId ?? DEFAULT_Y_AXIS_ID) === axisId)
        // Per-axis contributions: bars contribute their stacked-top values when stacked, raw
        // otherwise; lines/areas always contribute raw. The value scale spans the union.
        const contributing: Series[] = []
        for (const s of axisSeries) {
            const stype = seriesTypeOf(s)
            if (stype === 'bar' && barLayout === 'stacked' && barStackedData?.has(s.key)) {
                contributing.push({ ...s, data: barStackedData.get(s.key)!.top })
            } else {
                contributing.push(s)
            }
        }
        yAxes[axisId] = {
            scale: buildComboValueScale(contributing, valueRange, tickCount, scaleType),
            position: axisIndex === 0 ? 'left' : 'right',
        }
    })

    const primaryAxisId = axisIds.includes(DEFAULT_Y_AXIS_ID) ? DEFAULT_Y_AXIS_ID : axisIds[0]
    const primary = yAxes[primaryAxisId]

    return { band, group, yAxes, y: primary.scale }
}

function buildComboValueScale(
    series: Series[],
    valueRange: [number, number],
    tickCount: number,
    scaleType: 'linear' | 'log'
): D3YScale {
    const range = seriesValueRange(series)
    if (range.count === 0) {
        return d3.scaleLinear().domain([0, 1]).range(valueRange)
    }
    let { min, max } = range
    if (scaleType === 'log' && isFinite(range.minPositive)) {
        return d3.scaleLog().domain(niceLogDomain(range.minPositive, max)).range(valueRange).clamp(true)
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
    return d3.scaleLinear().domain([min, max]).nice(tickCount).range(valueRange)
}

/** Partition visible series into bar vs line/area buckets, preserving input order within
 *  each bucket. Excluded series are dropped. */
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
