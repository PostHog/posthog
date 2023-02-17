import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { InsightLogicProps } from '~/types'

import { keyForInsightLogicProps } from './sharedUtils'
import { Node } from '~/queries/schema'
import { insightQueryEditorLogic } from 'scenes/insights/insightQueryEditorLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { isInsightVizNode } from '~/queries/utils'

import type { insightQueryLogicType } from './insightQueryLogicType'

export const insightQueryLogic = kea<insightQueryLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightQueryLogic', key]),
    connect((props: InsightLogicProps) => ({
        actions: [
            insightQueryEditorLogic(props),
            ['setQuery as insightEditorSetQuery'],
            insightDataLogic(props),
            ['setQuery as insightVizSetQuery'],
        ],
        values: [
            insightQueryEditorLogic(props),
            ['query as insightEditorQuery'],
            insightDataLogic(props),
            ['query as insightVizQuery'],
        ],
    })),
    actions({
        setQuery: (query: Node) => ({ query }),
    }),
    selectors({
        query: [
            (s) => [s.insightEditorQuery, s.insightVizQuery],
            (insightEditorQuery, insightVizQuery) => (insightEditorQuery ? insightEditorQuery : insightVizQuery),
        ],
    }),
    listeners(({ actions }) => ({
        setQuery: ({ query }) => {
            if (isInsightVizNode(query)) {
                actions.insightVizSetQuery(query)
            } else {
                actions.insightEditorSetQuery(query)
            }
        },
    })),
])
