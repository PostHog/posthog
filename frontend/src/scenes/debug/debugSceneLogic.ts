import { actions, kea, path, reducers } from 'kea'

import type { debugSceneLogicType } from './debugSceneLogicType'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { stringifiedExamples } from '~/queries/examples'

const DEFAULT_QUERY: string = stringifiedExamples['HogQLRaw']

export const debugSceneLogic = kea<debugSceneLogicType>([
    path(['scenes', 'query', 'debugSceneLogic']),
    actions({
        setQuery: (query: string) => ({ query: query }),
    }),
    reducers({
        query: [DEFAULT_QUERY, { setQuery: (_, { query }) => query }],
    }),
    actionToUrl({
        setQuery: ({ query }) => {
            return [urls.debugQuery(), {}, { q: query }, { replace: true }]
        },
    }),
    urlToAction(({ actions, values }) => ({
        [urls.debugQuery()]: (_, __, { q }) => {
            if (q && q !== values.query) {
                actions.setQuery(q)
            }
        },
    })),
])
