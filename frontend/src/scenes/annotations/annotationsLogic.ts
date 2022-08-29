import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils'
import type { annotationsLogicType } from './annotationsLogicType'
import { AnnotationScope, AnnotationType } from '~/types'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { dayjs } from 'lib/dayjs'

export const ANNOTATION_DAYJS_FORMAT = 'MMMM DD, YYYY h:mm A'

export const annotationScopeToName: Record<AnnotationScope, string> = {
    [AnnotationScope.Insight]: 'Insight',
    [AnnotationScope.Project]: 'Project',
    [AnnotationScope.Organization]: 'Organization',
}

export const annotationScopeToLevel: Record<AnnotationScope, number> = {
    [AnnotationScope.Insight]: 0,
    [AnnotationScope.Project]: 1,
    [AnnotationScope.Organization]: 2,
}

export interface AnnotationModalForm {
    dateMarker: dayjs.Dayjs
    scope: AnnotationType['scope']
    content: AnnotationType['content']
}

export type AnnotationData = Pick<AnnotationType, 'date_marker' | 'scope' | 'content' | 'dashboard_item'>
export type AnnotationDataWithoutInsight = Omit<AnnotationData, 'dashboard_item'>

export const annotationsLogic = kea<annotationsLogicType>([
    path(['scenes', 'annotations', 'annotationsPageLogic']),
    actions({
        deleteAnnotation: (annotation: AnnotationType) => ({ annotation }),
        loadAnnotationsNext: () => true,
        setNext: (next: string | null) => ({ next }),
        appendAnnotations: (annotations: AnnotationType[]) => ({ annotations }),
        replaceAnnotation: (annotation: AnnotationType) => ({ annotation }),
        openModalToCreateAnnotation: () => true,
        openModalToEditAnnotation: (annotation: AnnotationType) => ({ annotation }),
        closeModal: true,
    }),
    loaders(({ values, actions }) => ({
        annotations: {
            __default: [],
            loadAnnotations: async () => {
                const response = await api.annotations.list()
                actions.setNext(response.next || null)
                return response.results
            },
            createAnnotationGenerically: async (annotationData: AnnotationData) => {
                const createdAnnotation = await api.annotations.create(annotationData)
                actions.appendAnnotations([createdAnnotation])
            },
            updateAnnotation: async ({
                annotationId,
                annotationData,
            }: {
                annotationId: AnnotationType['id']
                annotationData: AnnotationDataWithoutInsight
            }) => {
                const updatedAnnotation = await api.annotations.update(annotationId, annotationData)
                actions.replaceAnnotation(updatedAnnotation)
            },
            deleteAnnotation: async ({ annotation }) => {
                await deleteWithUndo({
                    endpoint: api.annotations.determineDeleteEndpoint(),
                    object: { name: `${annotation.date_marker} annotation`, ...annotation },
                    callback: (undo, annotation) => {
                        if (undo) {
                            actions.appendAnnotations([annotation])
                        }
                    },
                })
                return values.annotations.filter((a) => a.id !== annotation.id)
            },
        },
    })),
    reducers(() => ({
        annotations: [
            [] as AnnotationType[],
            {
                appendAnnotations: (state, { annotations }) => [...state, ...annotations],
                replaceAnnotation: (state, { annotation }) => {
                    const copy = state.slice()
                    const index = copy.findIndex((iterationAnnotation) => iterationAnnotation.id === annotation.id)
                    copy[index] = annotation
                    return copy
                },
            },
        ],
        next: [
            null as string | null,
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
        isModalOpen: [
            false,
            {
                openModalToCreateAnnotation: () => true,
                openModalToEditAnnotation: () => true,
                closeModal: () => false,
            },
        ],
        existingModalAnnotation: [
            null as AnnotationType | null,
            {
                openModalToCreateAnnotation: () => null,
                openModalToEditAnnotation: (_, { annotation }) => annotation,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        openModalToEditAnnotation: ({ annotation: { date_marker, scope, content } }) => {
            actions.setAnnotationModalValues({
                dateMarker: dayjs(date_marker),
                scope,
                content,
            })
        },
        openModalToCreateAnnotation: () => {
            actions.resetAnnotationModal()
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
    })),
    forms(({ actions, values }) => ({
        annotationModal: {
            defaults: {
                dateMarker: dayjs(),
                content: '',
                scope: AnnotationScope.Project,
            } as AnnotationModalForm,
            errors: ({ content }) => ({
                content: !content ? 'An annotation must have text content.' : null,
            }),
            submit: async (data) => {
                const { dateMarker, content, scope } = data
                if (values.existingModalAnnotation) {
                    // updateAnnotation inlined so that isAnnotationModalSubmitting works
                    const updatedAnnotation = await api.annotations.update(values.existingModalAnnotation.id, {
                        date_marker: dateMarker.toISOString(),
                        content,
                        scope,
                    })
                    actions.replaceAnnotation(updatedAnnotation)
                } else {
                    // createAnnotationGenerically inlined so that isAnnotationModalSubmitting works
                    const createdAnnotation = await api.annotations.create({
                        date_marker: dateMarker.toISOString(),
                        content,
                        scope,
                    })
                    actions.appendAnnotations([createdAnnotation])
                }
                actions.closeModal()
            },
        },
    })),
    afterMount(({ actions }) => actions.loadAnnotations()),
])
