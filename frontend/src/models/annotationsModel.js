import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import moment from 'moment'

export const annotationsModel = kea({
    actions: ({ values }) => ({
        createAnnotation: (content, date_marker) => ({ content, date_marker, nextKey: values.nextKey }),
        deleteAnnotation: id => ({ id }),
        incrementKey: true,
        submitAnnotations: true,
        clearAnnotationsToCreate: true,
    }),
    loaders: () => ({
        annotations: {
            loadAnnotations: async ({ before, after }) => {
                const response = await api.get('api/annotations/?' + toParams({ before, after }))
                return response.results
            },
        },
    }),
    reducers: () => ({
        annotationsToCreate: [
            {},
            {
                createAnnotation: (state, { content, date_marker, nextKey }) => ({
                    ...state,
                    [nextKey]: { content, date_marker, created_at: moment() },
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
            0,
            {
                incrementKey: state => state + 1,
            },
        ],
    }),
    selectors: ({ selectors }) => ({
        annotationsList: [
            () => [selectors.annotationsToCreate],
            annotationsToCreate => {
                return Object.entries(annotationsToCreate).map(([key, value]) => ({
                    ...value,
                    id: parseInt(key),
                }))
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        createAnnotation: () => actions.incrementKey(),
        submitAnnotations: async () => {
            for (const data in Object.values(values.annotationsToCreate)) {
                await api.create('api/annotations', data)
            }
            actions.clearAnnotationsToCreate()
        },
    }),
})
