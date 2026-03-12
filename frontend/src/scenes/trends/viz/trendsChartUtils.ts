import { getBarColorFromStatus } from 'lib/colors'
import type { DataPoint, Series } from 'lib/hog-charts'
import { ciRanges, movingAverage } from 'lib/statistics'
import { capitalizeFirstLetter, hexToRGBA } from 'lib/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import type { IndexedTrendResult } from 'scenes/trends/types'

import type { TrendsFilter } from '~/queries/schema/schema-general'
import type { BreakdownKeyType, LifecycleToggle, TrendsFilterType } from '~/types'

/** Runtime fields added to IndexedTrendResult by the trends data pipeline. */
interface TrendsResultExtensions {
    hideTooltip?: boolean
    breakdownLabels?: string[]
    breakdownValues?: BreakdownKeyType[]
    compareLabels?: string[]
}

export {
    buildGoalLines,
    buildYAxis,
    resolveGroupTypeLabel,
    tooltipPointsToSeriesDatum,
} from 'scenes/insights/chartUtils'

const MAX_SERIES = 50

export interface BuildSeriesOptions {
    indexedResults: IndexedTrendResult[]
    isArea: boolean
    isLog10: boolean
    isStickiness: boolean
    incompletePoints: number
    showMultipleYAxes: boolean | undefined | null
    showTrendLines: boolean | undefined
    showConfidenceIntervals: boolean | undefined
    confidenceLevel: number
    showMovingAverage: boolean | undefined
    movingAverageIntervals: number
    getTrendsColor: (dataset: IndexedTrendResult) => string
    getTrendsHidden: (dataset: IndexedTrendResult) => boolean
}

export function buildTrendsSeries(opts: BuildSeriesOptions): Series[] {
    const { indexedResults } = opts
    if (!indexedResults?.length) {
        return []
    }

    const result: Series[] = []

    for (const [index, dataset] of indexedResults.entries()) {
        if (opts.getTrendsHidden(dataset)) {
            continue
        }

        if (result.length >= MAX_SERIES) {
            break
        }

        const color = opts.getTrendsColor(dataset)
        const isPrevious = !!dataset.compare && dataset.compare_label === 'previous'

        let data = dataset.data as number[]

        if (opts.isLog10 && Array.isArray(data)) {
            data = data.map((v) => (v === 0 ? 1e-10 : v))
        }

        if (opts.isStickiness && Array.isArray(data)) {
            const count = dataset.count
            data = data.map((v) => (typeof v === 'number' && count > 0 ? (v / count) * 100 : 0))
        }

        const days = (dataset.days as string[] | undefined) ?? []
        const incompleteStart = opts.incompletePoints > 0 ? data.length - opts.incompletePoints : Infinity
        const dataPoints: DataPoint[] = data.map((v, i) => ({
            x: days[i] ?? String(i),
            y: v,
            ...(i >= incompleteStart ? { status: 'incomplete' as const } : {}),
        }))

        const yAxisID = opts.showMultipleYAxes && index > 0 ? `y${index}` : 'y'

        result.push({
            label: dataset.label ?? `Series ${index}`,
            data: dataPoints,
            color: dataset.status
                ? getBarColorFromStatus(dataset.status as LifecycleToggle)
                : isPrevious
                  ? `${color}80`
                  : color,
            yAxisPosition:
                yAxisID.includes('right') || (opts.showMultipleYAxes && index > 0 && index % 2 !== 0)
                    ? 'right'
                    : 'left',
            fill: opts.isArea,
            trendLine: opts.showTrendLines,
            lineStyle: isPrevious ? 'dashed' : undefined,
            hideFromTooltip: (dataset as IndexedTrendResult & TrendsResultExtensions).hideTooltip ?? false,
            meta: {
                datasetIndex: index,
                action: dataset.action,
                actions: dataset.actions,
                breakdown_value: dataset.breakdown_value,
                breakdownLabels: (dataset as IndexedTrendResult & TrendsResultExtensions).breakdownLabels,
                breakdownValues: (dataset as IndexedTrendResult & TrendsResultExtensions).breakdownValues,
                compare_label: dataset.compare_label,
                compareLabels: (dataset as IndexedTrendResult & TrendsResultExtensions).compareLabels,
                persons_urls: dataset.persons_urls,
                days: dataset.days,
                labels: dataset.labels,
                filter: dataset.filter,
                status: dataset.status,
                id: dataset.id,
                count: dataset.count,
            },
        })

        if (opts.showConfidenceIntervals) {
            const [lower, upper] = ciRanges(dataset.data, opts.confidenceLevel / 100)
            result.push({
                label: `${dataset.label} (CI lower)`,
                data: lower.map((v, i) => ({ x: days[i] ?? String(i), y: v })),
                color,
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
            result.push({
                label: `${dataset.label} (CI upper)`,
                data: upper.map((v, i) => ({ x: days[i] ?? String(i), y: v })),
                color: hexToRGBA(color, 0.2),
                fill: true,
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
        }

        if (opts.showMovingAverage) {
            const movingAvgData = movingAverage(dataset.data, opts.movingAverageIntervals)
            result.push({
                label: `${dataset.label} (Moving avg)`,
                data: movingAvgData.map((v, i) => ({ x: days[i] ?? String(i), y: v })),
                color,
                lineStyle: 'dashed',
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
        }
    }

    return result
}

export function lifecycleSeriesLabel(datum: SeriesDatum): string {
    const parts = datum.label?.split(' - ')
    return capitalizeFirstLetter(parts?.[parts.length - 1] ?? datum.label ?? 'None')
}

export interface FormatTooltipCountOptions {
    isStickiness: boolean
    isPercentStackView: boolean
    trendsFilter: TrendsFilter | null | undefined | Partial<TrendsFilterType>
    indexedResults: IndexedTrendResult[]
    seriesData: SeriesDatum[]
}

export function formatTooltipCount(value: number, opts: FormatTooltipCountOptions): string {
    if (opts.isStickiness) {
        const datum = opts.seriesData.find((s) => s.count === value)

        if (datum) {
            const origDataset = opts.indexedResults[datum.datasetIndex]
            const origValue = origDataset?.data?.[datum.dataIndex]

            if (origValue !== undefined && origValue !== null) {
                return `${value.toFixed(1)}% (${formatAggregationAxisValue(opts.trendsFilter, origValue)})`
            }
        }

        return `${value.toFixed(1)}%`
    }

    if (!opts.isPercentStackView) {
        return formatAggregationAxisValue(opts.trendsFilter, value)
    }

    const total = opts.seriesData.reduce((a, b) => a + b.count, 0)
    const pct = parseFloat(((value / total) * 100).toFixed(1))

    if (Number.isNaN(pct)) {
        return formatAggregationAxisValue(opts.trendsFilter, value)
    }

    return `${formatAggregationAxisValue(opts.trendsFilter, value)} (${pct}%)`
}
