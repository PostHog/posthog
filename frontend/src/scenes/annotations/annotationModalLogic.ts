import { actions, connect, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { AnnotationScope, AnnotationType } from '~/types'
import { forms } from 'kea-forms'
import { dayjs } from 'lib/dayjs'
import { annotationsModel } from '~/models/annotationsModel'
import type { annotationModalLogicType } from './annotationModalLogicType'
import { teamLogic } from 'scenes/teamLogic'

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

export const annotationModalLogic = kea<annotationModalLogicType>([
    path(['scenes', 'annotations', 'annotationModalLogic']),
    connect({
        actions: [
            annotationsModel,
            ['loadAnnotationsNext', 'replaceAnnotation', 'appendAnnotations', 'deleteAnnotation'],
        ],
        values: [
            annotationsModel,
            ['annotations', 'annotationsLoading', 'next', 'loadingNext'],
            teamLogic,
            ['timezone'],
        ],
    }),
    actions({
        openModalToCreateAnnotation: (initialDate?: dayjs.Dayjs) => ({ initialDate }),
        openModalToEditAnnotation: (annotation: AnnotationType) => ({ annotation }),
        closeModal: true,
    }),
    reducers(() => ({
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
    listeners(({ actions }) => ({
        openModalToEditAnnotation: ({ annotation: { date_marker, scope, content } }) => {
            actions.setAnnotationModalValues({
                dateMarker: dayjs(date_marker),
                scope,
                content,
            })
        },
        openModalToCreateAnnotation: ({ initialDate }) => {
            actions.resetAnnotationModal()
            if (initialDate) {
                actions.setAnnotationModalValue('dateMarker', initialDate)
            }
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
                    // annotationsModel's updateAnnotation inlined so that isAnnotationModalSubmitting works
                    const updatedAnnotation = await api.annotations.update(values.existingModalAnnotation.id, {
                        date_marker: dateMarker.tz(values.timezone).toISOString(),
                        content,
                        scope,
                    })
                    actions.replaceAnnotation(updatedAnnotation)
                } else {
                    // annotationsModel's createAnnotationGenerically inlined so that isAnnotationModalSubmitting works
                    const createdAnnotation = await api.annotations.create({
                        date_marker: dateMarker.tz(values.timezone).toISOString(),
                        content,
                        scope,
                    })
                    actions.appendAnnotations([createdAnnotation])
                }
                actions.closeModal()
            },
        },
    })),
])
