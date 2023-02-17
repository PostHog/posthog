import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'
import { InsightLogicProps } from '~/types'

import type { insightQueryEditorLogicType } from './insightQueryEditorLogicType'
import { keyForInsightLogicProps } from './sharedUtils'
import { Node } from '~/queries/schema'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isInsightVizNode } from '~/queries/utils'

export interface InsightQueryEditorLogicProps extends InsightLogicProps {
    query?: Node
}

export const insightQueryEditorLogic = kea<insightQueryEditorLogicType>([
    props({} as InsightQueryEditorLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightQueryEditorLogic', key]),
    connect((props: InsightQueryEditorLogicProps) => ({
        actions: [insightLogic(props as InsightLogicProps), ['setQuery as setInsightQuery']],
    })),
    actions({
        setQuery: (query: Node) => ({ query }),
    }),
    reducers(({ props }) => ({
        query: [
            props.query,
            {
                setQuery: (_, { query }) => query,
            },
        ],
    })),
    listeners(({ actions }) => ({
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                // insight viz is handled elsewhere
                return
            }
            actions.setInsightQuery(query)
        },
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!!props.query && props.query !== oldProps.query) {
            actions.setQuery(props.query)
        }
    }),
])
