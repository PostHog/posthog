import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import moment from 'moment'
import _ from 'lodash'
import { deleteWithUndo } from 'lib/utils'

export const annotationsLogic = kea({
    key: props => (props.pageKey ? `${props.pageKey}_annotations` : 'annotations_default'),
    actions: () => ({
        createAnnotation: (content, date_marker) => ({
            content,
            date_marker,
            created_at: moment(),
        }),
        createAnnotationNow: (content, date_marker) => ({
            content,
            date_marker,
            created_at: moment(),
        }),
        deleteAnnotation: id => ({ id }),
        clearAnnotationsToCreate: true,
    }),
    loaders: ({ props }) => ({
        annotations: {
            __default: [],
            loadAnnotations: async ({ before, after }) => {
                const params = {
                    ...(before ? { before } : {}),
                    ...(after ? { after } : {}),
                    ...(props.pageKey ? { dashboardItemId: props.pageKey } : {}),
                }
                const response = await api.get('api/annotation/?' + toParams(params))
                return response.results
            },
        },
    }),
    reducers: () => ({
        annotations: {
            createAnnotationNow: (state, { content, date_marker, created_at }) => [
                ...state,
                { id: getNextKey(state), content, date_marker, created_at },
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
            [],
            {
                createAnnotation: (state, { content, date_marker, created_at }) => [
                    ...state,
                    { id: getNextKey(state), content, date_marker, created_at },
                ],
                clearAnnotationsToCreate: () => ({}),
                deleteAnnotation: (state, { id }) => {
                    if (id < 0) {
                        let newState = [...state]
                        _.remove(newState, { id })
                        return newState
                    } else {
                        return state
                    }
                },
            },
        ],
    }),
    selectors: ({ selectors }) => ({
        annotationsList: [
            () => [selectors.annotationsToCreate, selectors.annotations],
            (annotationsToCreate, annotations) => {
                const result = [
                    ...annotationsToCreate.map(val => ({
                        ...val,
                        id: parseInt(val.id),
                    })),
                    ...annotations.map(val => ({
                        ...val,
                        id: parseInt(val.id),
                    })),
                ]
                return result
            },
        ],
    }),
    listeners: ({ actions, values, props }) => ({
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

function getNextKey(arr) {
    if (arr.length === 0) return -1
    const result = arr.reduce((prev, curr) => (prev.id < curr.id ? prev : curr))
    if (result.id >= 0) return -1
    else return minObj.id - 1
}
