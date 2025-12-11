import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { isTrendsQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import type { sessionLevelAggregationFilterLogicType } from './sessionLevelAggregationFilterLogicType'

export const sessionLevelAggregationFilterLogic = kea<sessionLevelAggregationFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'sessionLevelAggregationFilterLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['querySource']],
        actions: [insightVizDataLogic(props), ['updateQuerySource']],
    })),
    actions({
        setSessionLevelAggregation: (enabled: boolean) => ({ enabled }),
    }),
    reducers({
        sessionLevelAggregation: [
            false as boolean,
            {
                setSessionLevelAggregation: (_, { enabled }) => enabled,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setSessionLevelAggregation: () => {
            if (isTrendsQuery(values.querySource)) {
                actions.updateQuerySource({
                    trendsFilter: {
                        ...values.querySource.trendsFilter,
                        sessionLevelAggregation: values.sessionLevelAggregation || undefined,
                    },
                } as any)
            }
        },
    })),
    subscriptions(({ values, actions }) => ({
        querySource: (querySource) => {
            if (isTrendsQuery(querySource)) {
                const newSessionLevelAggregation = querySource.trendsFilter?.sessionLevelAggregation || false
                if (newSessionLevelAggregation !== values.sessionLevelAggregation) {
                    actions.setSessionLevelAggregation(newSessionLevelAggregation)
                }
            }
        },
    })),
])
