import { connect, kea, key, path, props, selectors } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { ChartDisplayType, InsightLogicProps } from '~/types'

import type { insightsTableDataLogicType } from './insightsTableDataLogicType'

export enum AggregationType {
    Total = 'total',
    Average = 'average',
    Median = 'median',
}

export const insightsTableDataLogic = kea<insightsTableDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'InsightsTable', 'insightsTableDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['isTrends', 'display', 'series', 'detailedResultsAggregationType as persistedAggregationType'],
        ],
        actions: [insightVizDataLogic(props), ['setDetailedResultsAggregationType']],
    })),

    selectors({
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
    }),
])
