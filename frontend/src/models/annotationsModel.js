import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import moment from 'moment'
import { getNextKey } from 'lib/components/Annotations/utils'

export const annotationsModel = kea({
    actions: () => ({
        createGlobalAnnotation: (content, date_marker, apply_all = false) => ({
            content,
            date_marker,
            created_at: moment(),
            apply_all,
        }),
        deleteGlobalAnnotation: (id) => ({ id }),
    }),
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
    reducers: () => ({
        globalAnnotations: {
            createGlobalAnnotation: (state, { content, date_marker, created_at, apply_all }) => [
                ...state,
                { id: getNextKey(state), content, date_marker, created_at, created_by: 'local', apply_all },
            ],
            deleteGlobalAnnotation: (state, { id }) => {
                if (id >= 0) {
                    return state.filter((a) => a.id !== id)
                } else {
                    return state
                }
            },
        },
    }),
    listeners: () => ({
        deleteGlobalAnnotation: async ({ id }) => {
            id >= 0 &&
                deleteWithUndo({
                    endpoint: 'annotation',
                    object: { name: 'Annotation', id },
                })
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadGlobalAnnotations,
    }),
})
