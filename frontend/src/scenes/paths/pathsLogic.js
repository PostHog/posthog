import { kea } from 'kea'
import { toParams } from 'lib/utils'
import api from 'lib/api'

export const pathsLogic = kea({
    loaders: ({ values }) => ({
        paths: {
            __default: {
                nodes: [],
                links: [],
            },
            loadPaths: async (_, breakpoint) => {
                const params = toParams(values.filter)
                const paths = await api.get(`api/paths${params ? `/?${params}` : ''}`)
                const response = {
                    nodes: [
                        ...paths.map(path => ({ name: path.source, id: path.source_id })),
                        ...paths.map(path => ({ name: path.target, id: path.target_id })),
                    ],
                    links: paths,
                }
                breakpoint()
                return response
            },
        },
    }),

    reducers: () => ({
        filter: [
            {
                dateFrom: null,
                dateTo: null,
            },
            {
                setFilter: (state, filter) => ({ ...state, ...filter }),
            },
        ],
        properties: [
            {},
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
    }),

    actions: () => ({
        setProperties: properties => ({ properties }),
        setFilter: filter => filter,
    }),

    listeners: ({ actions }) => ({
        setProperties: () => {
            actions.loadPaths()
        },
        setFilter: () => {
            actions.loadPaths()
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadPaths,
    }),
})
