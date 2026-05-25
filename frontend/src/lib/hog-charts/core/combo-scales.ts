import * as d3 from 'd3'

import { niceLogDomain, seriesValueRange, type StackedBand, yTickCountForHeight } from './scales'
import type { ChartDimensions, Series, SeriesType } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

type D3YScale = d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>

/** Combo chart scale set — a shared band x-axis (so bars have width and lines plot at band
 *  centers) plus per-axis value scales whose domain spans every series on that axis,
 *  regardless of type. */
export interface ComboScaleSet {
    band: d3.ScaleBand<string>
    /** Per-axis y scales keyed by axis id. Always populated (even for single-axis charts)
     *  so combo draw code only has one lookup path. */
    yAxes: Record<string, { scale: D3YScale; position: 'left' | 'right' }>
    /** Primary y scale — matches the default axis when present, otherwise the first axis. */
    y: D3YScale
    /** Sub-band for grouped bar layout — built from bar-series keys only. Undefined for
     *  stacked layout. Lines and areas do not participate in the group scale. */
    group?: d3.ScaleBand<string>
}

/** Brand for the ComboChart `ChartScales._private` slot — populated by ComboChart and
 *  narrowed by its draw callbacks and tooltip wrapper. Single source of truth so a
 *  shape change in `ComboScaleSet` doesn't drift between consumers. */
export interface ComboChartPrivate {
    __comboChart: ComboScaleSet
}

export interface CreateComboScalesOptions {
    scaleType?: 'linear' | 'log'
    barLayout?: 'stacked' | 'grouped'
    bandPadding?: number
    groupPadding?: number
    /** Resolves a series's effective type (`Series.type` ?? config default). */
    seriesTypeOf: (series: Series) => SeriesType
    /** Stacked-band data for bar series. Required when `barLayout` is `'stacked'`. */
    barStackedData?: Map<string, StackedBand>
}

/** Resolve a series's rendering type, honoring `Series.type` and falling back to `defaultType`. */
export function resolveSeriesType(series: Pick<Series, 'type'>, defaultType: SeriesType): SeriesType {
    return series.type ?? defaultType
}

/** True when the resolved type is `'line'` or `'area'`. */
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

    const axisIds = collectAxisIds(series)
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

/** DEFAULT_Y_AXIS_ID first when present, then remaining axis ids in first-encountered order. */
function collectAxisIds(series: Series[]): string[] {
    const set = new Set<string>()
    for (const s of series) {
        if (s.visibility?.excluded) {
            continue
        }
        set.add(s.yAxisId ?? DEFAULT_Y_AXIS_ID)
    }
    if (set.size === 0) {
        // Empty chart still needs an axis to draw against.
        set.add(DEFAULT_Y_AXIS_ID)
    }
    return [
        ...(set.has(DEFAULT_Y_AXIS_ID) ? [DEFAULT_Y_AXIS_ID] : []),
        ...Array.from(set).filter((id) => id !== DEFAULT_Y_AXIS_ID),
    ]
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
    const min = range.min > 0 ? 0 : range.min
    const max = range.max < 0 ? 0 : range.max
    if (scaleType === 'log' && isFinite(range.minPositive)) {
        return d3.scaleLog().domain(niceLogDomain(range.minPositive, max)).range(valueRange).clamp(true)
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
