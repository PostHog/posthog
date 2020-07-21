import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'

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
        deleteAnnotation: (id) => ({ id }),
    }),
    listeners: ({ actions }) => ({
        updateAnnotation: async ({ id, content }) => {
            await api.update(`api/annotation/${id}`, { content })
        },
        deleteAnnotation: ({ id }) => {
            deleteWithUndo({
                endpoint: 'annotation',
                object: { name: 'Annotation', id },
                callback: () => actions.loadAnnotations({}),
            })
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadAnnotations,
    }),
})
