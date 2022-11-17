import { actions, kea, path, reducers, selectors } from 'kea'

import type { querySceneLogicType } from './querySceneLogicType'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { Node } from '~/queries/nodes'
import { stringExamples } from 'scenes/query/examples'

const DEFAULT_QUERY: string = stringExamples['Events']
function prettyJSON(source: string): string {
    try {
        return JSON.stringify(JSON.parse(source), null, 2) + '\n'
    } catch (e) {
        return source
    }
}
export const querySceneLogic = kea<querySceneLogicType>([
    path(['scenes', 'query', 'querySceneLogic']),
    actions({
        setQuery: (query: string) => ({ query: prettyJSON(query) }),
        setQueryInput: (queryInput: string) => ({ queryInput }),
    }),
    reducers({
        query: [DEFAULT_QUERY, { setQuery: (_, { query }) => query }],
        queryInput: [
            DEFAULT_QUERY,
            { setQuery: (_, { query }) => query, setQueryInput: (_, { queryInput }) => queryInput },
        ],
    }),
    actionToUrl({
        setQuery: ({ query }) => {
            return [urls.query(), {}, { q: query }, { replace: true }]
        },
    }),
    urlToAction(({ actions, values }) => ({
        [urls.query()]: (_, __, { q }) => {
            if (q && q !== values.queryInput) {
                actions.setQuery(q)
            }
        },
    })),
    selectors({
        parsedQuery: [
            (s) => [s.query],
            (query): { JSONQuery: Node | null; error: string | null } => {
                let JSONQuery: Node | null = null
                let error = null
                try {
                    JSONQuery = JSON.parse(query)
                } catch (e: any) {
                    error = e.message
                }
                return { JSONQuery, error }
            },
        ],
        JSONQuery: [(s) => [s.parsedQuery], ({ JSONQuery }): Node | null => JSONQuery],
        error: [(s) => [s.parsedQuery], ({ error }): string | null => error],
        inputChanged: [(s) => [s.query, s.queryInput], (query, queryInput) => query !== queryInput],
    }),
])
