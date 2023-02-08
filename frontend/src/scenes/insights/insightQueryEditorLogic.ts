import { actions, kea, key, path, props, reducers } from 'kea'
import { InsightLogicProps } from '~/types'

import type { insightQueryEditorLogicType } from './insightQueryEditorLogicType'
import { keyForInsightLogicProps } from './sharedUtils'

export const insightQueryEditorLogic = kea<insightQueryEditorLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightQueryEditorLogic', key]),
    actions({
        setQuery: (query: string) => ({ query }),
    }),
    reducers(() => ({
        query: [
            '',
            {
                setQuery: (_, { query }) => {
                    console.log('setting query...', query)
                    return query
                },
            },
        ],
    })),
])
