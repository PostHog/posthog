import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { ChartDisplayType, CompareLabelType, InsightLogicProps } from '~/types'

import type { insightsTableDataLogicType } from './insightsTableDataLogicType'

export enum AggregationType {
    Total = 'total',
    Average = 'average',
    Median = 'median',
}

export function compareResultKey(item: IndexedTrendResult): string {
    return JSON.stringify([item.action?.order ?? 0, item.label ?? '', item.breakdown_value ?? ''])
}

export const insightsTableDataLogic = kea<insightsTableDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'InsightsTable', 'insightsTableDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['isTrends', 'display', 'series', 'detailedResultsAggregationType as persistedAggregationType'],
            trendsDataLogic(props),
            ['indexedResults', 'compareFilter'],
        ],
        actions: [insightVizDataLogic(props), ['setDetailedResultsAggregationType']],
    })),

    actions({
        toggleColumnPin: (columnKey: string) => ({ columnKey }),
    }),

    reducers({
        pinnedBreakdownColumns: [
            [] as string[],
            { persist: true },
            {
                toggleColumnPin: (state, { columnKey }) => {
                    if (state.includes(columnKey)) {
                        return state.filter((k) => k !== columnKey)
                    }
                    return [...state, columnKey]
                },
            },
        ],
    }),

    selectors({
        pinnedColumns: [
            (s) => [s.pinnedBreakdownColumns],
            (pinnedBreakdownColumns): string[] => {
                return ['label', ...pinnedBreakdownColumns]
            },
        ],
        isColumnPinned: [
            (s) => [s.pinnedBreakdownColumns],
            (pinnedBreakdownColumns) =>
                (columnKey: string): boolean => {
                    return pinnedBreakdownColumns.includes(columnKey)
                },
        ],
        /** Only allow table aggregation options when the math is total volume
         * otherwise double counting will happen when the math is set to unique.
         * Except when view type is Table or WorldMap */
        allowAggregation: [
            (s) => [s.isTrends, s.display, s.series],
            (isTrends, display, series) => {
                if (isTrends && (display === ChartDisplayType.ActionsTable || display === ChartDisplayType.WorldMap)) {
                    return true
                }

                return !!series?.every((entity) => entity.math === 'total' || entity.math === 'sum' || !entity.math)
            },
        ],
        aggregation: [
            (s) => [s.series, s.persistedAggregationType],
            (series, persistedAggregationType) => {
                if (persistedAggregationType) {
                    return persistedAggregationType
                }

                const hasMathUniqueFilter = !!series?.find(({ math }) => math === 'dau')
                return hasMathUniqueFilter ? AggregationType.Average : AggregationType.Total
            },
        ],
        previousResultMap: [
            (s) => [s.compareFilter, s.indexedResults],
            (compareFilter, indexedResults): Map<string, IndexedTrendResult> => {
                if (!compareFilter?.compare) {
                    return new Map()
                }
                const map = new Map<string, IndexedTrendResult>()
                for (const result of indexedResults) {
                    if (result.compare_label === CompareLabelType.Previous) {
                        map.set(compareResultKey(result), result)
                    }
                }
                return map
            },
        ],
        getPreviousResult: [
            (s) => [s.compareFilter, s.previousResultMap],
            (compareFilter, previousResultMap) =>
                (item: IndexedTrendResult): IndexedTrendResult | undefined => {
                    if (!compareFilter?.compare) {
                        return undefined
                    }
                    return previousResultMap.get(compareResultKey(item))
                },
        ],
        displayResults: [
            (s) => [s.compareFilter, s.indexedResults],
            (compareFilter, indexedResults): IndexedTrendResult[] => {
                if (compareFilter?.compare) {
                    return indexedResults.filter((r) => r.compare_label === CompareLabelType.Current)
                }
                return indexedResults
            },
        ],
    }),
])
