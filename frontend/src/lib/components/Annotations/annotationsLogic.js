import { kea } from 'kea'
import api from 'lib/api'
import moment from 'moment'
import { determineDifferenceType, deleteWithUndo, toParams, groupBy } from '~/lib/utils'
import { annotationsModel } from '~/models/annotationsModel'
import { getNextKey } from './utils'

export const annotationsLogic = kea({
    key: (props) => (props.pageKey ? `${props.pageKey}_annotations` : 'annotations_default'),
    connect: {
        actions: [annotationsModel, ['loadGlobalAnnotations', 'deleteGlobalAnnotation', 'createGlobalAnnotation']],
        values: [annotationsModel, ['activeGlobalAnnotations']],
    },
    actions: () => ({
        createAnnotation: (content, date_marker, scope = 'dashboard_item') => ({
            content,
            date_marker,
            created_at: moment(),
            scope,
        }),
        createAnnotationNow: (content, date_marker, scope = 'dashboard_item') => ({
            content,
            date_marker,
            created_at: moment(),
            scope,
        }),
        deleteAnnotation: (id) => ({ id }),
        clearAnnotationsToCreate: true,
        updateDiffType: (dates) => ({ dates }),
        setDiffType: (type) => ({ type }),
    }),
    loaders: ({ props }) => ({
        annotations: {
            __default: [],
            loadAnnotations: async ({ before, after }) => {
                const params = {
                    ...(before ? { before } : {}),
                    ...(after ? { after } : {}),
                    ...(props.pageKey ? { dashboardItemId: props.pageKey } : {}),
                    scope: 'dashboard_item',
                    deleted: false,
                }
                const response = await api.get('api/annotation/?' + toParams(params))
                return response.results
            },
        },
    }),
    reducers: () => ({
        annotations: {
            createAnnotationNow: (state, { content, date_marker, created_at, scope }) => [
                ...state,
                { id: getNextKey(state), content, date_marker, created_at, created_by: 'local', scope },
            ],
            deleteAnnotation: (state, { id }) => {
                if (id >= 0) {
                    return state.filter((a) => a.id !== id)
                } else {
                    return state
                }
            },
        },
        annotationsToCreate: [
            [],
            {
                createAnnotation: (state, { content, date_marker, created_at, scope }) => [
                    ...state,
                    {
                        id: getNextKey(state),
                        content,
                        date_marker,
                        created_at,
                        created_by: 'local',
                        scope,
                    },
                ],
                clearAnnotationsToCreate: () => [],
                deleteAnnotation: (state, { id }) => {
                    if (id < 0) {
                        return state.filter((a) => a.id !== id)
                    } else {
                        return state
                    }
                },
            },
        ],
        diffType: [
            'day',
            {
                setDiffType: (_, { type }) => type,
            },
        ],
    }),
    selectors: ({ selectors }) => ({
        annotationsList: [
            () => [selectors.annotationsToCreate, selectors.annotations, selectors.activeGlobalAnnotations],
            (annotationsToCreate, annotations, activeGlobalAnnotations) => {
                const result = [
                    ...annotationsToCreate.map((val) => ({
                        ...val,
                        id: parseInt(val.id),
                    })),
                    ...annotations.map((val) => ({
                        ...val,
                        id: parseInt(val.id),
                    })),
                    ...activeGlobalAnnotations.map((val) => ({
                        ...val,
                        id: parseInt(val.id),
                    })),
                ]
                return result
            },
        ],
        groupedAnnotations: [
            () => [selectors.annotationsList, selectors.diffType],
            (annotationsList, diffType) =>
                groupBy(annotationsList, (annotation) => moment(annotation['date_marker']).startOf(diffType)),
        ],
    }),
    listeners: ({ actions, props }) => ({
        createAnnotationNow: async ({ content, date_marker, created_at, scope }) => {
            await api.create('api/annotation', {
                content,
                date_marker: moment(date_marker),
                created_at,
                dashboard_item: props.pageKey,
                scope,
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
        updateDiffType: ({ dates }) => {
            actions.setDiffType(determineDifferenceType(dates[0], dates[1]))
        },
    }),
    events: ({ actions, props }) => ({
        afterMount: () => props.pageKey && actions.loadAnnotations({}),
    }),
})
