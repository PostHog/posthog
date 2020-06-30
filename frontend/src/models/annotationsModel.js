import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import moment from 'moment'

export const annotationsModel = kea({
    key: props => props.pageKey || 'default',
    actions: ({ values }) => ({
        createAnnotation: (content, date_marker) => ({
            content,
            date_marker,
            nextKey: values.nextKey,
            created_at: moment(),
        }),
        createAnnotationNow: (content, date_marker) => ({
            content,
            date_marker,
            nextKey: values.nextKey,
            created_at: moment(),
        }),
        deleteAnnotation: id => ({ id }),
        incrementKey: true,
        submitAnnotations: true,
        clearAnnotationsToCreate: true,
    }),
    loaders: ({ props }) => ({
        annotations: {
            __default: [],
            loadAnnotations: async ({ before, after }) => {
                let params = {}
                if (before) {
                    params = {
                        ...params,
                        before,
                    }
                }
                if (after) {
                    params = {
                        ...params,
                        after,
                    }
                }
                if (props.pageKey) {
                    params = {
                        ...params,
                        dashboardItemId: props.pageKey,
                    }
                }
                const response = await api.get('api/annotation/?' + toParams(params))
                return response.results
            },
        },
    }),
    reducers: () => ({
        annotations: {
            createAnnotationNow: (state, { content, date_marker, nextKey, created_at }) => ({
                ...state,
                [nextKey]: { content, date_marker, created_at },
            }),
        },
        annotationsToCreate: [
            {},
            {
                createAnnotation: (state, { content, date_marker, nextKey, created_at }) => ({
                    ...state,
                    [nextKey]: { content, date_marker, created_at },
                }),
                clearAnnotationsToCreate: () => ({}),
                deleteAnnotation: (state, { id }) => {
                    let newState = { ...state }
                    delete newState[id]
                    return newState
                },
            },
        ],
        nextKey: [
            -1,
            {
                incrementKey: state => state - 1,
            },
        ],
    }),
    selectors: ({ selectors }) => ({
        annotationsList: [
            () => [selectors.annotationsToCreate, selectors.annotations],
            (annotationsToCreate, annotations) => {
                let toCreate = Object.entries(annotationsToCreate).map(([key, value]) => ({
                    ...value,
                    id: parseInt(key),
                }))
                let retrieved = Object.entries(annotations).map(([key, value]) => ({
                    ...value,
                    id: parseInt(key),
                }))
                return toCreate.concat(retrieved)
            },
        ],
    }),
    listeners: ({ actions, values, props }) => ({
        createAnnotation: () => actions.incrementKey(),
        submitAnnotations: async () => {
            for (const data in Object.values(values.annotationsToCreate)) {
                await api.create('api/annotation', data)
            }
            actions.clearAnnotationsToCreate()
        },
        createAnnotationNow: async ({ content, date_marker, created_at }) => {
            await api.create('api/annotation', {
                content,
                date_marker: moment(date_marker),
                created_at,
                dashboard_item: props.pageKey,
            })
        },
    }),
    events: ({ actions, props }) => ({
        afterMount: () => props.pageKey && actions.loadAnnotations({}),
    }),
})
