import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { InsightLogicProps } from '~/types'

import type { insightQueryEditorLogicType } from './insightQueryEditorLogicType'
import { keyForInsightLogicProps } from './sharedUtils'
import { Node } from '~/queries/schema'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isInsightVizNode } from '~/queries/utils'

export const insightQueryEditorLogic = kea<insightQueryEditorLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightQueryEditorLogic', key]),
    connect((props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setQuery as setInsightQuery', 'setActiveView']],
        values: [insightLogic(props), ['query as insightQuery']],
    })),
    actions({
        setQuery: (query: Node) => ({ query }),
    }),
    reducers(({ values }) => ({
        query: [
            values.insightQuery,
            {
                setQuery: (_, { query }) => query,
                setInsightQuery: (_, { query }) => query,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                // insight viz is handled elsewhere
                return
            }
            actions.setInsightQuery(query)
        },
        setActiveView: () => {
            if (!!values.insightQuery && values.insightQuery !== values.query) {
                actions.setQuery(values.insightQuery)
            }
        },
    })),
])
