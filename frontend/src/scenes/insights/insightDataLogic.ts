import { kea, props, key, path, actions, reducers, selectors } from 'kea'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema'
import { BaseMathType } from '~/types'
import { ShownAsValue } from 'lib/constants'

import type { insightDataLogicType } from './insightDataLogicType'

const getDefaultQuery = (): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.LifecycleQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: '$pageview',
                event: '$pageview',
                math: BaseMathType.TotalCount,
            },
        ],
        lifecycleFilter: { shown_as: ShownAsValue.LIFECYCLE },
    },
})

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    actions({
        setQuery: (query: InsightVizNode) => ({ query }),
        setQuerySourceMerge: (query: Omit<Partial<InsightQueryNode>, 'kind'>) => ({ query }),
    }),

    reducers({
        query: [
            getDefaultQuery() as InsightVizNode,
            {
                setQuery: (_, { query }) => query,
                setQuerySourceMerge: (query, { query: querySource }) => ({
                    ...query,
                    source: { ...query.source, ...querySource },
                }),
            },
        ],
    }),

    selectors({
        querySource: [(s) => [s.query], (query) => query.source],
    }),
])
