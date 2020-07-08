import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'

export const annotationsModel = kea({
    loaders: () => ({
        globalAnnotations: {
            __default: [],
            loadGlobalAnnotations: async () => {
                const response = await api.get(
                    'api/annotation/?' +
                        toParams({
                            apply_all: true,
                        })
                )
                return response.results
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadGlobalAnnotations,
    }),
})
