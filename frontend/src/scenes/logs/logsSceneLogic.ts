import { actions, kea, path, reducers } from 'kea'

import { LogsQuery, NodeKind } from '~/queries/schema'

import type { logsSceneLogicType } from './logsSceneLogicType'

const DEFAULT_QUERY: LogsQuery = {
    kind: NodeKind.LogsQuery,
    dateRange: {
        date_from: '-7d',
    },
}

export const logsSceneLogic = kea<logsSceneLogicType>([
    path(['scenes', 'logs', 'logsSceneLogic']),
    actions({
        setQuery: (query: Partial<LogsQuery>) => ({ query }),
    }),
    reducers({
        query: [
            DEFAULT_QUERY,
            {
                setQuery: (state, { query }) => ({ ...state, ...query }),
            },
        ],
    }),
])
