import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
import { insightLogic } from '../insights/insightLogic'
import { InsightLogicProps, TrendResult, TrendsFilterType, LifecycleFilterType, StickinessFilterType } from '~/types'
import type { trendsLogicType } from './trendsLogicType'

import {
    isLifecycleFilter,
    isStickinessFilter,
    isTrendsInsight,
    keyForInsightLogicProps,
} from 'scenes/insights/sharedUtils'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

export const trendsLogic = kea<trendsLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('all_trends')),
    path((key) => ['scenes', 'trends', 'trendsLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters as inflightFilters', 'insight', 'insightLoading']],
    })),

    actions(() => ({
        loadMoreBreakdownValues: true,
        setBreakdownValuesLoading: (loading: boolean) => ({ loading }),
    })),

    reducers({
        breakdownValuesLoading: [
            false,
            {
                setBreakdownValuesLoading: (_, { loading }) => loading,
            },
        ],
    }),

    selectors({
        filters: [
            (s) => [s.inflightFilters],
            (
                inflightFilters
            ): Partial<TrendsFilterType> | Partial<StickinessFilterType> | Partial<LifecycleFilterType> =>
                inflightFilters &&
                (isTrendsFilter(inflightFilters) ||
                    isStickinessFilter(inflightFilters) ||
                    isLifecycleFilter(inflightFilters))
                    ? inflightFilters
                    : {},
        ],
        results: [
            (s) => [s.insight],
            ({ filters, result }): TrendResult[] =>
                isTrendsInsight(filters?.insight) && Array.isArray(result) ? result : [],
        ],
        loadMoreBreakdownUrl: [
            (s) => [s.insight],
            ({ filters, next }) => (isTrendsInsight(filters?.insight) ? next : null),
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
    }),

    listeners(({ actions, values, props }) => ({
        loadMoreBreakdownValues: async () => {
            if (!values.loadMoreBreakdownUrl) {
                return
            }
            actions.setBreakdownValuesLoading(true)

            const { filters } = values
            const response = await api.get(values.loadMoreBreakdownUrl)
            insightLogic(props).actions.setInsight(
                {
                    ...values.insight,
                    result: [...values.results, ...(response.result ? response.result : [])],
                    filters: filters,
                    next: response.next,
                },
                {}
            )
            actions.setBreakdownValuesLoading(false)
        },
    })),
])
