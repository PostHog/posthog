import { type Series, mixColors } from '@posthog/quill-charts'

import { getSeriesColor } from 'lib/colors'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { formatSqlSeriesValue } from './sqlLineGraphAdapter'

export interface PieSlice {
    label: string
    value: number
    color: string
}

export type SqlPieYSeries = AxisSeries<number | null> | AxisBreakdownSeries<number | null>

const isBreakdownSeries = (series: SqlPieYSeries): series is AxisBreakdownSeries<number | null> => {
    return !('column' in series)
}

const toSliceLabel = (value: unknown): string => {
    if (value === null || value === undefined || value === '') {
        return '[No value]'
    }

    return String(value)
}

const sumValues = (values: (number | null)[]): number => {
    return values.reduce<number>((sum, value) => sum + (value ?? 0), 0)
}

/** The order pie wedges take palette entries in.
 *
 *  The data palette is ordered for lines and bars, where series sit apart on a canvas and a
 *  legend tells them apart. Pie wedges touch, so consecutive entries land edge to edge, and the
 *  palette holds several look-alike pairs: two saturated blues (#1d4aff, #0476fb), three teals
 *  (#42827e, #41cbc4, #30d5c8), and two purples (#621da6, #a56eff). This sequence cycles hue
 *  families so no pair sits within two positions of another member, at any slice count.
 *
 *  One exception, kept deliberately: #1d4aff leads so a pie still opens on the brand blue, which
 *  puts its twin last. A pie with exactly 15 slices therefore wraps one blue onto the other —
 *  between the largest and the smallest wedge, the least costly place for it to happen.
 *
 *  A palette resize invalidates the sequence. `sqlPieGraphAdapter.test.ts` asserts it still
 *  covers every entry exactly once, so the drift fails a test rather than degrading quietly. */
const SLICE_PALETTE_ORDER = [0, 4, 2, 11, 1, 6, 8, 10, 12, 13, 9, 3, 14, 5, 7]

/** Share of the palette color a slice keeps when it mixes toward the chart ground. A line or a
 *  bar needs full saturation to read at a few pixels wide. A pie fills large neighboring areas,
 *  where full strength across many wedges is what makes the chart tiring to look at. */
const SLICE_COLOR_STRENGTH = 0.74

/** Fallback color for the slice at `index`, in palette order rather than index order.
 *
 *  `ground` is the chart surface. Passing it mutes the palette color toward that surface. The
 *  blend happens here, not at draw time, for two reasons: a canvas 2D context cannot resolve
 *  `color-mix()`, and the legend glyph and tooltip swatch read this same resolved value, so
 *  mixing once keeps all three in agreement.
 */
const paletteSliceColor = (index: number, ground?: string): string => {
    const size = SLICE_PALETTE_ORDER.length
    // Past the palette a color has to repeat. Restart the walk from its midpoint so a repeat
    // lands away from its first use instead of beside it.
    const shift = Math.floor(index / size) * Math.floor(size / 2)
    const color = getSeriesColor(SLICE_PALETTE_ORDER[(index + shift) % size])
    return ground ? mixColors(color, ground, 1 - SLICE_COLOR_STRENGTH) : color
}

const getSeriesLabel = (series: SqlPieYSeries, index: number): string => {
    if (isBreakdownSeries(series)) {
        return series.name || `[Series ${index + 1}]`
    }

    return series.settings?.display?.label || series.column.name
}

/** One slice per y-series — the breakdown and no-categorical-x-axis cases share this shaping. */
const seriesToSlices = (yData: SqlPieYSeries[], ground?: string): PieSlice[] =>
    yData
        .map((series, index) => ({
            label: getSeriesLabel(series, index),
            value: sumValues(series.data),
            // A color the user picked stays exactly as picked; only the fallback is muted.
            color: series.settings?.display?.color ?? paletteSliceColor(index, ground),
        }))
        .filter((slice) => slice.value > 0)

export const buildPieSlices = (
    xData: AxisSeries<string> | null,
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[],
    ground?: string
): PieSlice[] => {
    if (!yData.length) {
        return []
    }

    if (yData.some(isBreakdownSeries)) {
        return seriesToSlices(yData, ground)
    }

    if (yData.length === 1 && xData && xData.column.name !== 'None') {
        const totalsByLabel = new Map<string, number>()

        xData.data.forEach((rawLabel, index) => {
            const label = toSliceLabel(rawLabel)
            const value = yData[0].data[index] ?? 0
            totalsByLabel.set(label, (totalsByLabel.get(label) ?? 0) + value)
        })

        return Array.from(totalsByLabel.entries())
            .map(([label, value], index) => ({
                label,
                value,
                color: paletteSliceColor(index, ground),
            }))
            .filter((slice) => slice.value > 0)
    }

    return seriesToSlices(yData, ground)
}

/** One quill `Series` per slice, with the slice's resolved color pinned so per-breakdown
 *  `resultCustomizations` survive the move off chart.js. */
export const buildPieSeries = (slices: PieSlice[]): Series[] => {
    return slices.map((slice, index) => ({
        key: `${slice.label}-${index}`,
        label: slice.label,
        color: slice.color,
        data: [slice.value],
    }))
}

export const formatPieSliceCount = (
    value: number,
    total: number,
    settings?: AxisSeriesSettings,
    asPercent = false
): string => {
    const formatted = formatSqlSeriesValue(value, settings)
    const shareOfTotal = total ? parseFloat(((value / total) * 100).toFixed(1)) : 0
    if (asPercent) {
        // Lead with the share, keep the absolute value as a secondary detail
        return total ? `${shareOfTotal}% (${formatted})` : formatted
    }
    // Percent-styled values are already a share, so a share-of-total suffix would be confusing
    if (!total || settings?.formatting?.style === 'percent') {
        return formatted
    }
    return `${formatted} (${shareOfTotal}%)`
}
