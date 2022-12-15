import { kea, props, key, path, actions, reducers } from 'kea'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { InsightVizNode, Node, NodeKind } from '~/queries/schema'
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
        setQuery: (query: Node) => ({ query }),
    }),

    reducers({ query: [getDefaultQuery() as Node, { setQuery: (_, { query }) => query }] }),
])
