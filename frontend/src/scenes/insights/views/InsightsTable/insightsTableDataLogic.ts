import { kea, props, key, path, connect, actions, reducers, selectors } from 'kea'

import { ChartDisplayType, InsightLogicProps } from '~/types'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

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
        values: [insightDataLogic(props), ['isTrends', 'display', 'series']],
    })),

    actions({
        setAggregationType: (type: AggregationType) => ({ type }),
    }),

    reducers({
        aggregationType: [
            null as AggregationType | null,
            {
                setAggregationType: (_, { type }) => type,
            },
        ],
    }),

    selectors({
        /** Only allow table aggregation options when the math is total volume
         * otherwise double counting will happen when the math is set to unique.
         * Except when view type is Table */
        allowAggregation: [
            (s) => [s.isTrends, s.display, s.series],
            (isTrends, display, series) => {
                if (isTrends && display === ChartDisplayType.ActionsTable) {
                    return true
                }

                return !!series?.every((entity) => entity.math === 'total' || entity.math === 'sum' || !entity.math)
            },
        ],
        aggregation: [
            (s) => [s.series, s.aggregationType],
            (series, aggregationType) => {
                if (aggregationType === null) {
                    const hasMathUniqueFilter = !!series?.find(({ math }) => math === 'dau')
                    return hasMathUniqueFilter ? AggregationType.Average : AggregationType.Total
                }

                return aggregationType
            },
        ],
    }),
])
