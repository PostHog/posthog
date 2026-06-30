import { type Series } from '@posthog/quill-charts'

import { getSeriesColor } from 'lib/colors'

import { ChartDisplayType } from '~/types'

import { AxisSeries, AxisSeriesSettings, formatDataWithSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'

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
            const value = yData[0].data[index] ?? 0
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

export const formatPieSliceCount = (
    value: number,
    total: number,
    settings?: AxisSeriesSettings,
    asPercent = false
): string => {
    const formatted = String(formatDataWithSettings(value, settings) ?? value)
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

export function canRenderSqlPieGraph(props: LineGraphProps): boolean {
    return props.visualizationType === ChartDisplayType.ActionsPie
}
