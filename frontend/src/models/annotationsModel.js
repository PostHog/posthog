import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import dayjs from 'dayjs'
import { getNextKey } from 'lib/components/Annotations/utils'

export const annotationsModel = kea({
    actions: () => ({
        createGlobalAnnotation: (content, date_marker, dashboard_item) => ({
            content,
            date_marker,
            created_at: dayjs(),
            dashboard_item,
        }),
        deleteGlobalAnnotation: (id) => ({ id }),
    }),
    loaders: ({ values }) => ({
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
            createGlobalAnnotation: async ({ dashboard_item, content, date_marker, created_at }) => {
                const annotation = await api.create('api/annotation', {
                    content,
                    date_marker: dayjs.isDayjs(date_marker) ? date_marker : dayjs(date_marker),
                    created_at,
                    dashboard_item,
                    scope: 'organization',
                })
                return [...(values.globalAnnotations || []), annotation]
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
        deleteGlobalAnnotation: ({ id }) => {
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
