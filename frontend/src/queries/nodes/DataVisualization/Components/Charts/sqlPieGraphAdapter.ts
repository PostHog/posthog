import { type Series } from '@posthog/quill-charts'

import { getSeriesColor } from 'lib/colors'
import { MAX_DEFAULT_PROPORTION_LEGEND_PARTS } from 'lib/constants'

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

export const isBreakdownSeries = (series: SqlPieYSeries): series is AxisBreakdownSeries<number | null> => {
    return !('column' in series)
}

const toSliceLabel = (value: unknown): string => {
    if (value === null || value === undefined || value === '') {
        return '[No value]'
    }

    return String(value)
}

// One NaN or Infinity point would otherwise make the whole category's sum non-finite.
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

const hasLabelColumn = (xData: AxisSeries<string> | null): xData is AxisSeries<string> =>
    !!xData && xData.column.name !== 'None'

export const drawsOnePartPerSeries = (xData: AxisSeries<string> | null, yData: SqlPieYSeries[]): boolean =>
    yData.length !== 1 || !hasLabelColumn(xData) || yData.some(isBreakdownSeries)

export const buildPieSlices = (
    xData: AxisSeries<string> | null,
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
): PieSlice[] => {
    if (!yData.length) {
        return []
    }

    if (drawsOnePartPerSeries(xData, yData) || !xData) {
        return seriesToSlices(yData)
    }

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

/** One quill `Series` per slice, with the slice's resolved color pinned so per-breakdown
 *  `resultCustomizations` survive the move off chart.js. */
export const buildPieSeries = (slices: PieSlice[]): Series[] => {
    // Keyed by label, not position, so a part hidden in the legend stays hidden when the results reorder.
    // A repeat skips a numbered key that another part has as its own label, so no two parts share a key.
    const labels = new Set(slices.map((slice) => slice.label))
    const usedKeys = new Set<string>()
    return slices.map((slice) => {
        let key = slice.label
        for (let count = 2; usedKeys.has(key) || (key !== slice.label && labels.has(key)); count++) {
            key = `${slice.label}-${count}`
        }
        usedKeys.add(key)
        return {
            key,
            label: slice.label,
            color: slice.color,
            data: [slice.value],
        }
    })
}

/** Pie charts can consume breakdown series totals directly, even when there isn't a matching
 *  breakdown x-axis to swap in like the line/bar path expects. */
export const partOfWholeChartData = (
    breakdown: BreakdownSeriesData<number | null>,
    xData: AxisSeries<string> | null,
    yData: AxisSeries<number | null>[]
): { xData: AxisSeries<string> | null; yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[] } => ({
    xData: breakdown.xData.data.length ? breakdown.xData : xData,
    yData: breakdown.seriesData.length ? breakdown.seriesData : yData,
})

export const showsLegendByDefault = (isProportionBar: boolean, partCount: number): boolean =>
    isProportionBar && partCount <= MAX_DEFAULT_PROPORTION_LEGEND_PARTS

/** The total is a sum-of-values readout, so it defaults on only when slices show values.
 *  `showPieTotal` is the legacy top-level toggle, honored for charts saved before `pie`. A proportion
 *  bar has no "show on slices" control, so a `sliceContent` left from a pie does not turn its total off. */
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
