import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { InsightLogicProps, InsightType } from '~/types'

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
        setQuery: (query: Node | null) => ({ query }),
    }),
    reducers(({ values }) => ({
        query: [
            values.insightQuery,
            {
                setQuery: (_, { query }) => query,
                setInsightQuery: (_, { query }) => query,
                setActiveView: (state, { type }) => (type !== InsightType.QUERY ? null : state),
            },
        ],
    })),
    listeners(({ actions }) => ({
        setQuery: ({ query }) => {
            if (isInsightVizNode(query ?? undefined)) {
                // insight viz is handled elsewhere
                return
            }
            actions.setInsightQuery(query)
        },
    })),
])
