import { actions, kea, path, reducers, selectors } from 'kea'

import type { querySceneLogicType } from './querySceneLogicType'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { Node } from '~/queries/nodes'
import { stringExamples } from 'scenes/query/examples'

const DEFAULT_QUERY: string = stringExamples['Events']

export const querySceneLogic = kea<querySceneLogicType>([
    path(['scenes', 'query', 'querySceneLogic']),
    actions({ setQueryInput: (queryInput: string) => ({ queryInput }) }),
    reducers({ queryInput: [DEFAULT_QUERY, { setQueryInput: (_, { queryInput }) => queryInput }] }),
    actionToUrl({ setQueryInput: ({ queryInput }) => [urls.query(), {}, { q: queryInput }, { replace: true }] }),
    urlToAction(({ actions, values }) => ({
        [urls.query()]: (_, __, { q }) => {
            if (q && q !== values.queryInput) {
                actions.setQueryInput(q)
            }
        },
    })),
    selectors({
        parsedQuery: [
            (s) => [s.queryInput],
            (queryInput): { JSONQuery: Node | null; error: string | null } => {
                let JSONQuery: Node | null = null
                let error = null
                try {
                    JSONQuery = JSON.parse(queryInput)
                } catch (e: any) {
                    error = e.message
                }
                return { JSONQuery, error }
            },
        ],
        JSONQuery: [(s) => [s.parsedQuery], ({ JSONQuery }): Node | null => JSONQuery],
        error: [(s) => [s.parsedQuery], ({ error }): string | null => error],
    }),
])
