import { scaleBand, type ScaleBand } from 'd3-scale'

import { createYScale, type D3YScale, groupVisibleSeriesByAxis, orderedAxisPositions, type StackedBand } from './scales'
import type { ChartDimensions, Series, SeriesType, ValueDomain } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

/** Combo chart scale set — a band x-axis plus per-axis value scales spanning every series on
 *  that axis. `yAxes` is always populated (even for single-axis charts) so combo draw code has
 *  one lookup path. `group` is the sub-band for grouped bar layout, built from bar-series keys
 *  only — lines/areas don't participate.
 *
 *  `value` aliases the primary axis scale so the set is structurally a `BarScaleSet` and can be
 *  passed straight into the shared bar helpers (`computeBarAtIndex`, `bandCenter`, `resolveBarsAtCursor`);
 *  `y`/`yAxes` let `resolveYScaleForSeries` resolve a series' own axis scale. */
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
    barLayout?: 'stacked' | 'grouped' | 'percent'
    bandPadding?: number
    groupPadding?: number
    seriesTypeOf: (series: Series) => SeriesType
    /** Stacked-band data for bar series. Required when `barLayout` is `'stacked'`. */
    barStackedData?: Map<string, StackedBand>
    /** Applied to the primary (default/left) axis only — goal lines (`{ include }`) render against
     *  the primary axis, so secondary axes keep their own data-derived scale. See {@link ValueDomain}. */
    valueDomain?: ValueDomain
    /** Per-axis overrides — explicit values win over the alternating-side default and
     *  `options.scaleType`. `startAtZero: false` is ignored for axes carrying bar series. */
    axes?: { id: string; position?: 'left' | 'right'; scaleType?: 'linear' | 'log'; startAtZero?: boolean }[]
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
        valueDomain,
        axes,
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

    // Empty chart still needs an axis to draw against.
    const axisOverrides = new Map((axes ?? []).map((a) => [a.id, a]))
    const axisPositions = orderedAxisPositions(series).map(({ axisId, position }) => ({
        axisId,
        position: axisOverrides.get(axisId)?.position ?? position,
    }))
    if (axisPositions.length === 0) {
        axisPositions.push({ axisId: DEFAULT_Y_AXIS_ID, position: 'left' })
    }
    const primaryAxisId = axisPositions.some((a) => a.axisId === DEFAULT_Y_AXIS_ID)
        ? DEFAULT_Y_AXIS_ID
        : axisPositions[0].axisId

    const seriesByAxis = groupVisibleSeriesByAxis(series)
    const yAxes: ComboScaleSet['yAxes'] = {}
    for (const { axisId, position } of axisPositions) {
        const axisSeries = seriesByAxis.get(axisId) ?? []
        // Per-axis contributions: bars contribute their stacked-top values when stacked, raw
        // otherwise; lines/areas always contribute raw. The value scale spans the union.
        const axisValueSeries: Series[] = axisSeries.map((s) => {
            const stacked = barStackedData?.get(s.key)
            if (seriesTypeOf(s) === 'bar' && (barLayout === 'stacked' || barLayout === 'percent') && stacked) {
                return { ...s, data: stacked.top }
            }
            return s
        })
        // `createYScale` applies the shared overlay baseline clamp, degenerate `min === max`
        // guard, log fallback, and `{ include }` goal-line domain extension — primary axis only.
        // Percent-clamp only axes that actually carry bar series — a line/area-only axis (e.g. a
        // series explicitly routed to the right axis) keeps its own data-derived scale instead of
        // being forced onto [0, 1].
        const hasBarSeries = axisSeries.some((s) => seriesTypeOf(s) === 'bar')
        const scale = createYScale(axisValueSeries, dimensions, {
            scaleType: axisOverrides.get(axisId)?.scaleType ?? scaleType,
            percentStack: barLayout === 'percent' && hasBarSeries,
            valueDomain: axisId === primaryAxisId ? valueDomain : undefined,
            floatBaseline: !hasBarSeries && axisOverrides.get(axisId)?.startAtZero === false,
        })
        yAxes[axisId] = { scale, position }
    }

    const primary = yAxes[primaryAxisId].scale

    return { band, group, yAxes, y: primary, value: primary }
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
