import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import moment from 'moment'
import _ from 'lodash'
import { deleteWithUndo } from 'lib/utils'

export const annotationsLogic = kea({
    key: props => (props.pageKey && props.pageKey + '_annotations') || 'annotations_default',
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
            createAnnotationNow: (state, { content, date_marker, nextKey, created_at }) => [
                ...state,
                { id: nextKey, content, date_marker, created_at },
            ],
            deleteAnnotation: (state, { id }) => {
                if (id >= 0) {
                    let newState = [...state]
                    _.remove(newState, { id })
                    return newState
                } else {
                    return state
                }
            },
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
                    if (id < 0) {
                        let newState = { ...state }
                        delete newState[id]
                        return newState
                    } else {
                        return state
                    }
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
                let retrieved = annotations.map(val => ({
                    ...val,
                    id: parseInt(val.id),
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
            actions.loadAnnotations({})
        },
        deleteAnnotation: async ({ id }) => {
            id >= 0 &&
                deleteWithUndo({
                    endpoint: 'annotation',
                    object: { name: 'Annotation', id },
                    callback: () => actions.loadAnnotations({}),
                })
        },
    }),
    events: ({ actions, props }) => ({
        afterMount: () => props.pageKey && actions.loadAnnotations({}),
    }),
})
