import { actions, kea, path, reducers } from 'kea'

import type { querySceneLogicType } from './querySceneLogicType'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { stringifiedExamples } from '~/queries/examples'

const DEFAULT_QUERY: string = stringifiedExamples['Events']

export const querySceneLogic = kea<querySceneLogicType>([
    path(['scenes', 'query', 'querySceneLogic']),
    actions({
        setQuery: (query: string) => ({ query: query }),
    }),
    reducers({
        query: [DEFAULT_QUERY, { setQuery: (_, { query }) => query }],
    }),
    actionToUrl({
        setQuery: ({ query }) => {
            return [urls.query(), {}, { q: query }, { replace: true }]
        },
    }),
    urlToAction(({ actions, values }) => ({
        [urls.query()]: (_, __, { q }) => {
            if (q && q !== values.query) {
                actions.setQuery(q)
            }
        },
    })),
])
