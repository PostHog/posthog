/**
 * Trends-specific utilities for the TrendsChart hog-charts consumer.
 *
 * For shared chart utilities (tooltip bridging, y-axis, goal lines, etc.)
 * see scenes/insights/chartUtils.ts.
 */

import { getBarColorFromStatus } from 'lib/colors'
import type { Series } from 'lib/hog-charts'
import { ciRanges, movingAverage } from 'lib/statistics'
import { capitalizeFirstLetter, hexToRGBA } from 'lib/utils'

import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import type { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import type { IndexedTrendResult } from 'scenes/trends/types'

import type { TrendsFilter } from '~/queries/schema/schema-general'
import type { LifecycleToggle, TrendsFilterType } from '~/types'

// Re-export shared utilities so existing TrendsChart imports don't break
export { buildGoalLines, buildYAxis, resolveGroupTypeLabel, tooltipPointsToSeriesDatum } from 'scenes/insights/chartUtils'

const MAX_SERIES = 50

export interface BuildSeriesOptions {
    indexedResults: IndexedTrendResult[]
    isBar: boolean
    isArea: boolean
    isLog10: boolean
    isStickiness: boolean
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
            data = data.map((v) => (typeof v === 'number' ? (v / count) * 100 : v))
        }

        const yAxisID = opts.showMultipleYAxes && index > 0 ? `y${index}` : 'y'

        result.push({
            label: dataset.label ?? `Series ${index}`,
            data,
            color: dataset.status
                ? getBarColorFromStatus(dataset.status as LifecycleToggle)
                : isPrevious
                  ? `${color}80`
                  : color,
            displayType: opts.isBar ? 'bar' : 'line',
            yAxisPosition:
                yAxisID.includes('right') || (opts.showMultipleYAxes && index > 0 && index % 2 !== 0)
                    ? 'right'
                    : 'left',
            fill: opts.isArea,
            trendLine: opts.showTrendLines,
            borderDash: isPrevious ? [6, 4] : undefined,
            borderWidth: opts.isBar ? 0 : 2,
            pointRadius: Array.isArray(data) && data.length === 1 ? 4 : 0,
            hideFromTooltip: (dataset as any).hideTooltip ?? false,
            meta: {
                datasetIndex: index,
                action: dataset.action,
                actions: dataset.actions,
                breakdown_value: dataset.breakdown_value,
                breakdownLabels: (dataset as any).breakdownLabels,
                breakdownValues: (dataset as any).breakdownValues,
                compare_label: dataset.compare_label,
                compareLabels: (dataset as any).compareLabels,
                persons_urls: dataset.persons_urls,
                days: dataset.days,
                labels: dataset.labels,
                filter: dataset.filter,
                status: dataset.status,
                id: dataset.id,
                count: dataset.count,
                _dataset: dataset,
            },
        })

        if (opts.showConfidenceIntervals) {
            const [lower, upper] = ciRanges(dataset.data, opts.confidenceLevel / 100)
            result.push({
                label: `${dataset.label} (CI lower)`,
                data: lower,
                color,
                borderWidth: 0,
                pointRadius: 0,
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
            result.push({
                label: `${dataset.label} (CI upper)`,
                data: upper,
                color: hexToRGBA(color, 0.2),
                fill: true,
                borderWidth: 0,
                pointRadius: 0,
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
        }

        if (opts.showMovingAverage) {
            const movingAvgData = movingAverage(dataset.data, opts.movingAverageIntervals)
            result.push({
                label: `${dataset.label} (Moving avg)`,
                data: movingAvgData,
                color,
                borderDash: [10, 3],
                borderWidth: 2,
                pointRadius: 0,
                hideFromTooltip: true,
                meta: { auxiliary: true },
            })
        }
    }

    return result
}

export function getCompareLabels(indexedResults: IndexedTrendResult[]): string[] {
    if (
        indexedResults.length === 2 &&
        indexedResults.every((x) => x.compare) &&
        indexedResults.find((x) => x.compare_label === 'current')?.labels
    ) {
        return indexedResults.find((x) => x.compare_label === 'current')!.labels!
    }
    return indexedResults[0]?.labels ?? []
}

/** Extract the lifecycle status from a label like "Pageview - returning" → "Returning". */
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

/** Format a tooltip value with stickiness percentages, percent stack view, or default aggregation. */
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
