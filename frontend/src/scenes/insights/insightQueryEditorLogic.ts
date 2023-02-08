import { actions, kea, key, path, props, reducers } from 'kea'
import { InsightLogicProps } from '~/types'

import type { insightQueryEditorLogicType } from './insightQueryEditorLogicType'
import { keyForInsightLogicProps } from './sharedUtils'
import { Node } from '~/queries/schema'

export const insightQueryEditorLogic = kea<insightQueryEditorLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightQueryEditorLogic', key]),
    actions({
        setQuery: (query: Node) => ({ query }),
    }),
    reducers(() => ({
        query: [
            undefined as Node | undefined,
            {
                setQuery: (_, { query }) => query,
            },
        ],
    })),
])
