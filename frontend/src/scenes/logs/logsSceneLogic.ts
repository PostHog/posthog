import { actions, kea, listeners, path, reducers } from 'kea'

import { LogsQuery, NodeKind } from '~/queries/schema'
import { AnyPropertyFilter, EventPropertyFilter } from '~/types'

import type { logsSceneLogicType } from './logsSceneLogicType'

const DEFAULT_QUERY: LogsQuery = {
    kind: NodeKind.LogsQuery,
    dateRange: {
        date_from: '-7d',
    },
    properties: [],
}

export const logsSceneLogic = kea<logsSceneLogicType>([
    path(['scenes', 'logs', 'logsSceneLogic']),
    actions({
        setQuery: (query: Partial<LogsQuery>) => ({ query }),
        addFilter: (filter: EventPropertyFilter) => ({ filter }),
    }),
    reducers({
        query: [
            DEFAULT_QUERY,
            {
                setQuery: (state, { query }) => ({ ...state, ...query }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        addFilter: ({ filter }) => {
            const propValues = (values.query.properties as AnyPropertyFilter[]) ?? []

            actions.setQuery({
                properties: [...propValues, filter],
            })
        },
    })),
])
