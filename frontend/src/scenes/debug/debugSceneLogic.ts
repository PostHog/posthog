import { actions, kea, path, reducers } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import { stringifiedExamples } from '~/queries/examples'

import type { debugSceneLogicType } from './debugSceneLogicType'

const DEFAULT_QUERY: string = stringifiedExamples['HogQLRaw']

export const debugSceneLogic = kea<debugSceneLogicType>([
    path(['scenes', 'query', 'debugSceneLogic']),
    actions({
        setQuery1: (query: string) => ({ query: query }),
        setQuery2: (query: string) => ({ query: query }),
    }),
    reducers({
        query1: [DEFAULT_QUERY, { setQuery1: (_, { query }) => query }],
        query2: [DEFAULT_QUERY, { setQuery2: (_, { query }) => query }],
    }),
    actionToUrl(({ values }) => ({
        setQuery1: ({ query }) => {
            return [
                urls.debugQuery(),
                {},
                { q: query, ...(values.query2 ? { q2: values.query2 } : {}) },
                { replace: true },
            ]
        },
        setQuery2: () => {
            return [urls.debugQuery(), {}, { q: values.query1, q2: values.query2 }, { replace: true }]
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.debugQuery()]: (_, __, { q, q2 }) => {
            if (q && q !== values.query1) {
                actions.setQuery1(q)
            }
            if ((q2 ?? '') !== (values.query2 ?? '')) {
                actions.setQuery2(q2 ?? '')
            }
        },
    })),
])
