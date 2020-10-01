import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'

export const annotationsTableLogic = kea({
    loaders: ({ actions }) => ({
        annotations: {
            __default: [],
            loadAnnotations: async () => {
                const response = await api.get('api/annotation/?' + toParams({ order: '-updated_at' }))
                actions.setNext(response.next)
                return response.results
            },
        },
    }),
    reducers: () => ({
        annotations: {
            appendAnnotations: (state, { annotations }) => [...state, ...annotations],
        },
        next: [
            null,
            {
                setNext: (_, { next }) => next,
            },
        ],
        loadingNext: [
            false,
            {
                loadAnnotationsNext: () => true,
                appendAnnotations: () => false,
            },
        ],
    }),
    actions: () => ({
        updateAnnotation: (id, content) => ({ id, content }),
        deleteAnnotation: (id) => ({ id }),
        restoreAnnotation: (id) => ({ id }),
        loadAnnotationsNext: () => true,
        setNext: (next) => ({ next }),
        appendAnnotations: (annotations) => ({ annotations }),
    }),
    listeners: ({ actions, values }) => ({
        updateAnnotation: async ({ id, content }) => {
            await api.update(`api/annotation/${id}`, { content })
        },
        restoreAnnotation: async ({ id }) => {
            await api.update(`api/annotation/${id}`, { deleted: false })
            actions.loadAnnotations({})
        },
        deleteAnnotation: ({ id }) => {
            deleteWithUndo({
                endpoint: 'annotation',
                object: { name: 'Annotation', id },
                callback: () => actions.loadAnnotations({}),
            })
        },
        loadAnnotationsNext: async () => {
            let results = []
            if (values.next) {
                const response = await api.get(values.next)
                actions.setNext(response.next)
                results = response.results
            }
            actions.appendAnnotations(results)
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadAnnotations,
    }),
})
