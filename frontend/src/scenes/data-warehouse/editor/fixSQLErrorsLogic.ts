import { actions, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { fixSQLErrorsLogicType } from './fixSQLErrorsLogicType'

export interface Response {
    query: string
    trace_id: string
    error?: string
}

export const fixSQLErrorsLogic = kea<fixSQLErrorsLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'fixSQLErrorsLogic']),
    actions({
        fixErrors: (query: string, error?: string) => ({ query, error }),
    }),
    loaders({
        response: [
            null as Response | null,
            {
                fixErrors: async ({ query, error }) => {
                    const response = await api.fixHogQLErrors.fix(query, error)

                    return response as Response
                },
            },
        ],
    }),
])
