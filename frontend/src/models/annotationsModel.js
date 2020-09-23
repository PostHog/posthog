import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import moment from 'moment'
import { getNextKey } from 'lib/components/Annotations/utils'

export const annotationsModel = kea({
    actions: () => ({
        createGlobalAnnotation: (content, date_marker, dashboard_item) => ({
            content,
            date_marker,
            created_at: moment(),
            dashboard_item,
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
                            scope: 'organization',
                            deleted: false,
                        })
                )
                return response.results
            },
        },
    }),
    reducers: () => ({
        globalAnnotations: {
            createGlobalAnnotation: (state, { content, date_marker, created_at }) => [
                ...state,
                { id: getNextKey(state), content, date_marker, created_at, created_by: 'local', scope: 'organization' },
            ],
            deleteGlobalAnnotation: (state, { id }) => {
                return state.filter((a) => a.id !== id)
            },
        },
    }),
    selectors: ({ selectors }) => ({
        activeGlobalAnnotations: [
            () => [selectors.globalAnnotations],
            (globalAnnotations) => {
                return globalAnnotations.filter((annotation) => !annotation.deleted)
            },
        ],
    }),
    listeners: ({ actions }) => ({
        createGlobalAnnotation: async ({ dashboard_item, content, date_marker, created_at }) => {
            await api.create('api/annotation', {
                content,
                date_marker: moment.isMoment(date_marker) ? date_marker : moment(date_marker),
                created_at,
                dashboard_item,
                scope: 'organization',
            })
            actions.loadGlobalAnnotations()
        },
        deleteGlobalAnnotation: async ({ id }) => {
            id >= 0 &&
                deleteWithUndo({
                    endpoint: 'annotation',
                    object: { name: 'Annotation', id },
                    callback: () => actions.loadGlobalAnnotations({}),
                })
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadGlobalAnnotations,
    }),
})
