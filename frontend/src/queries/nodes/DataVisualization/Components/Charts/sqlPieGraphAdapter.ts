import { type Series } from '@posthog/quill-charts'

import { getSeriesColor } from 'lib/colors'

import { ChartSettings } from '~/queries/schema/schema-general'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries, BreakdownSeriesData } from '../seriesBreakdownLogic'
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

// Treats null, NaN, and Infinity as a missing value worth 0. Otherwise one non-finite point
// poisons the whole category's sum, dropping an otherwise-valid total from the chart entirely.
const toFiniteValue = (value: number | null): number => (value !== null && Number.isFinite(value) ? value : 0)

const sumValues = (values: (number | null)[]): number => {
    return values.reduce<number>((sum, value) => sum + toFiniteValue(value), 0)
}

const getSeriesLabel = (series: SqlPieYSeries, index: number): string => {
    if (isBreakdownSeries(series)) {
        return series.name || `[Series ${index + 1}]`
    }

    return series.settings?.display?.label || series.column.name
}

/** One slice per y-series — the breakdown and no-categorical-x-axis cases share this shaping. */
const seriesToSlices = (yData: SqlPieYSeries[]): PieSlice[] =>
    yData
        .map((series, index) => ({
            label: getSeriesLabel(series, index),
            value: sumValues(series.data),
            color: series.settings?.display?.color ?? getSeriesColor(index),
        }))
        .filter((slice) => slice.value > 0)

export const buildPieSlices = (
    xData: AxisSeries<string> | null,
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
): PieSlice[] => {
    if (!yData.length) {
        return []
    }

    if (yData.some(isBreakdownSeries)) {
        return seriesToSlices(yData)
    }

    if (yData.length === 1 && xData && xData.column.name !== 'None') {
        const totalsByLabel = new Map<string, number>()

        xData.data.forEach((rawLabel, index) => {
            const label = toSliceLabel(rawLabel)
            const value = toFiniteValue(yData[0].data[index])
            totalsByLabel.set(label, (totalsByLabel.get(label) ?? 0) + value)
        })

        return Array.from(totalsByLabel.entries())
            .map(([label, value], index) => ({
                label,
                value,
                color: getSeriesColor(index),
            }))
            .filter((slice) => slice.value > 0)
    }

    return seriesToSlices(yData)
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

/** The data a part-of-whole chart draws. Pie charts can consume breakdown series totals directly,
 *  even when there isn't a matching breakdown x-axis to swap in like the line/bar path expects. */
export const partOfWholeChartData = (
    breakdown: BreakdownSeriesData<number | null>,
    xData: AxisSeries<string> | null,
    yData: AxisSeries<number | null>[]
): { xData: AxisSeries<string> | null; yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[] } => ({
    xData: breakdown.xData.data.length ? breakdown.xData : xData,
    yData: breakdown.seriesData.length ? breakdown.seriesData : yData,
})

/** Past this many parts, one legend row per part costs more than it helps, so the legend starts off. */
export const MAX_DEFAULT_PROPORTION_LEGEND_PARTS = 20

/** The legend default when the user has not set one. A proportion bar has no axis to read a size
 *  from, so its legend carries the shares and shows while the part count stays small. */
export const showsLegendByDefault = (isProportionBar: boolean, partCount: number): boolean =>
    isProportionBar && partCount <= MAX_DEFAULT_PROPORTION_LEGEND_PARTS

/** Whether the total shows. The total is a sum-of-values readout, so it defaults on only when
 *  slices show values. `showPieTotal` is the legacy top-level toggle, honored for charts saved
 *  before `pie`. A proportion bar has no "show on slices" control, so a `sliceContent` left over
 *  from a prior pie or donut does not turn its total off. The renderer and the Display tab switch
 *  both read this, so they agree. */
export const showsPieTotal = (
    chartSettings: Pick<ChartSettings, 'pie' | 'showPieTotal'>,
    isProportionBar: boolean
): boolean =>
    chartSettings.pie?.showTotal ??
    chartSettings.showPieTotal ??
    (isProportionBar || (chartSettings.pie?.sliceContent ?? 'values') === 'values')

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
