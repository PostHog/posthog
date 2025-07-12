import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjsUtcToTimezone } from 'lib/dayjs'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'

import { AnnotationType, RawAnnotationType } from '~/types'

import type { annotationsModelType } from './annotationsModelType'

export type AnnotationData = Pick<RawAnnotationType, 'date_marker' | 'scope' | 'content' | 'dashboard_item'>
export type AnnotationDataWithoutInsight = Omit<AnnotationData, 'dashboard_item'>

export function deserializeAnnotation(annotation: RawAnnotationType, projectTimezone: string): AnnotationType {
    return {
        ...annotation,
        date_marker: annotation.date_marker ? dayjsUtcToTimezone(annotation.date_marker, projectTimezone) : null,
        created_at: dayjsUtcToTimezone(annotation.created_at, projectTimezone),
    }
}

export function serializeAnnotation(annotation: AnnotationType): RawAnnotationType {
    return {
        ...annotation,
        date_marker: annotation.date_marker ? annotation.date_marker.toISOString() : null,
        created_at: annotation.created_at.toISOString(),
    }
}

export const annotationsModel = kea<annotationsModelType>([
    path(['models', 'annotationsModel']),
    connect(() => ({ values: [teamLogic, ['currentTeam', 'timezone']] })),
    actions({
        deleteAnnotation: (annotation: AnnotationType) => ({ annotation }),
        loadAnnotationsNext: () => true,
        setNext: (next: string | null) => ({ next }),
        appendAnnotations: (annotations: RawAnnotationType[]) => ({ annotations }),
        replaceAnnotation: (annotation: RawAnnotationType) => ({ annotation }),
    }),
    loaders(({ values, actions }) => ({
        rawAnnotations: {
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
                annotationId: RawAnnotationType['id']
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
                            actions.appendAnnotations([serializeAnnotation(annotation)])
                        }
                    },
                })
                return values.annotations.filter((a) => a.id !== annotation.id)
            },
        },
    })),
    reducers(() => ({
        rawAnnotations: [
            [] as RawAnnotationType[],
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
    selectors({
        annotations: [
            (s) => [s.rawAnnotations, s.timezone],
            (rawAnnotations, timezone): AnnotationType[] => {
                return rawAnnotations.map((annotation): AnnotationType => deserializeAnnotation(annotation, timezone))
            },
        ],
        annotationsLoading: [(s) => [s.rawAnnotationsLoading], (rawAnnotationsLoading) => rawAnnotationsLoading],
    }),
    listeners(({ actions, values }) => ({
        loadAnnotationsNext: async () => {
            let results: RawAnnotationType[] = []
            if (values.next) {
                const response = await api.get(values.next)
                actions.setNext(response.next)
                results = response.results
            }
            actions.appendAnnotations(results)
        },
    })),
    afterMount(({ values, actions }) => {
        if (isAuthenticatedTeam(values.currentTeam)) {
            // Don't load on shared insights/dashboards
            actions.loadAnnotations()
        }
    }),
    permanentlyMount(),
])
