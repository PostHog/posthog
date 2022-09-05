import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils'
import type { annotationsModelType } from './annotationsModelType'
import { AnnotationType } from '~/types'
import { loaders } from 'kea-loaders'

export type AnnotationData = Pick<AnnotationType, 'date_marker' | 'scope' | 'content' | 'dashboard_item'>
export type AnnotationDataWithoutInsight = Omit<AnnotationData, 'dashboard_item'>

export const annotationsModel = kea<annotationsModelType>([
    path(['models', 'annotationsModel']),
    actions({
        deleteAnnotation: (annotation: AnnotationType) => ({ annotation }),
        loadAnnotationsNext: () => true,
        setNext: (next: string | null) => ({ next }),
        appendAnnotations: (annotations: AnnotationType[]) => ({ annotations }),
        replaceAnnotation: (annotation: AnnotationType) => ({ annotation }),
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
    })),
    listeners(({ actions, values }) => ({
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
    afterMount(({ actions }) => actions.loadAnnotations()),
])
