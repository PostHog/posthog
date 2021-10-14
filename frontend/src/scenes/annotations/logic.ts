import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import { annotationsModel } from '~/models/annotationsModel'
import { annotationsTableLogicType } from './logicType'
import { AnnotationType } from '~/types'
import { ProjectBasedLogicProps, getProjectBasedLogicKeyBuilder } from 'lib/utils/logics'

export const annotationsTableLogic = kea<annotationsTableLogicType>({
    props: {} as ProjectBasedLogicProps,
    key: getProjectBasedLogicKeyBuilder(),
    loaders: ({ actions, props }) => ({
        annotations: {
            __default: [],
            loadAnnotations: async () => {
                const response = await api.get(
                    `api/projects/${props.teamId}/annotations/?${toParams({ order: '-updated_at' })}`
                )
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
        appendAnnotations: (annotations: AnnotationType[]) => ({ annotations }),
    }),
    listeners: ({ actions, values, props }) => ({
        updateAnnotation: async ({ id, content }) => {
            await api.update(`api/projects/${props.teamId}/annotations/${id}`, { content })
            actions.loadAnnotations()
        },
        restoreAnnotation: async ({ id }) => {
            await api.update(`api/projects/${props.teamId}/annotations/${id}`, { deleted: false })
            actions.loadAnnotations()
        },
        deleteAnnotation: ({ id }) => {
            deleteWithUndo({
                endpoint: `projects/${props.teamId}/annotations`,
                object: { name: 'Annotation', id },
                callback: () => actions.loadAnnotations(),
            })
        },
        loadAnnotationsNext: async () => {
            let results: AnnotationType[] = []
            if (values.next) {
                const response = await api.get(values.next)
                actions.setNext(response.next)
                results = response.results
            }
            actions.appendAnnotations(results)
        },
        [annotationsModel({ teamId: props.teamId }).actionTypes.createGlobalAnnotationSuccess]: () => {
            actions.loadAnnotations()
        },
    }),
    events: ({ actions, props }) => ({
        afterMount: () => props.teamId && actions.loadAnnotations(),
    }),
})
