import { actions, events, kea, key, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { NodeKind } from '~/queries/schema'

export const hogFunctionReplayLogic = kea([
    key(({ id }) => id),
    path((key) => ['scenes', 'pipeline', 'hogFunctionReplayLogic', key]),
    actions({}),
    loaders(({  }) => ({

    })),
    reducers({

    }),
    selectors(({  }) => ({

    })),
    loaders(({  }) => ({
        events: [
            null as string[] | null,
            {
                loadEvents: async () => {
                    const query = {
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: "EventsQuery",
                            fixedProperties: [
                                {
                                    type: "AND",
                                    values: [
                                        {
                                            type: "OR",
                                            values: []
                                        }
                                    ]
                                }
                            ],
                            select: [
                                "*"
                            ],
                            after: "-7d",
                            orderBy: [
                                "timestamp DESC"
                            ]
                        }
                    }
                    const response = await api.query(query) as any
                    response.results = response.results.map((x: any) => ({ ...x[0], retries: [] }))
                    return response
                },
            },
        ],
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadEvents({ refresh: 'blocking' })
        },
    })),
])
