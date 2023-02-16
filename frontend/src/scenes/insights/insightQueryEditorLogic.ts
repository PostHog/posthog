import { actions, kea, key, path, props, propsChanged, reducers } from 'kea'
import { InsightLogicProps } from '~/types'

import type { insightQueryEditorLogicType } from './insightQueryEditorLogicType'
import { keyForInsightLogicProps } from './sharedUtils'
import { Node } from '~/queries/schema'

export interface InsightQueryEditorLogicProps extends InsightLogicProps {
    query?: Node
}

export const insightQueryEditorLogic = kea<insightQueryEditorLogicType>([
    props({} as InsightQueryEditorLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightQueryEditorLogic', key]),
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
    propsChanged(({ actions, props }, oldProps) => {
        if (!!props.query && props.query !== oldProps.query) {
            actions.setQuery(props.query)
        }
    }),
])
