import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'

export const annotationsTableLogic = kea({
    loaders: () => ({
        annotations: {
            __default: [],
            loadAnnotations: async () => {
                const response = await api.get('api/annotation/?' + toParams({ order: '-updated_at' }))
                return response.results
            },
        },
    }),
    actions: () => ({
        updateAnnotation: (id, content) => ({ id, content }),
    }),
    listeners: () => ({
        updateAnnotation: async ({ id, content }) => {
            await api.update(`api/annotation/${id}`, { content })
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadAnnotations,
    }),
})
