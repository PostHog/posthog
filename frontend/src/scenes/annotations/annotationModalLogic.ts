import { actions, connect, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { AnnotationScope, AnnotationType, InsightModel, AnnotationType } from '~/types'
import { forms } from 'kea-forms'
import { dayjs, Dayjs } from 'lib/dayjs'
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
    dateMarker: Dayjs
    scope: AnnotationType['scope']
    content: AnnotationType['content']
    dashboardItemId: AnnotationType['dashboard_item'] | null
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
        openModalToCreateAnnotation: (initialDate?: Dayjs | null, insightId?: InsightModel['id'] | null) => ({
            initialDate,
            insightId,
        }),
        openModalToEditAnnotation: (annotation: AnnotationType, insightId?: InsightModel['id'] | null) => ({
            annotation,
            insightId,
        }),
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
        onSavedInsight: [
            false,
            {
                openModalToCreateAnnotation: (_, { insightId }) => !!insightId,
                openModalToEditAnnotation: (_, { insightId }) => !!insightId,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        openModalToEditAnnotation: ({ annotation: { date_marker, scope, content } }) => {
            actions.setAnnotationModalValues({
                dateMarker: dayjs(date_marker).tz(values.timezone),
                scope,
                content,
            })
        },
        openModalToCreateAnnotation: ({ initialDate, insightId }) => {
            actions.resetAnnotationModal()
            if (initialDate) {
                actions.setAnnotationModalValue('dateMarker', initialDate)
            }
            if (insightId) {
                actions.setAnnotationModalValue('scope', AnnotationScope.Insight)
                actions.setAnnotationModalValue('dashboardItemId', insightId)
            }
        },
    })),
    forms(({ actions, values }) => ({
        annotationModal: {
            defaults: {
                dateMarker: dayjs().tz(values.timezone),
                content: '',
                scope: AnnotationScope.Project,
                dashboardItemId: null,
            } as AnnotationModalForm,
            errors: ({ content }) => ({
                content: !content ? 'An annotation must have text content.' : null,
            }),
            submit: async (data) => {
                const { dateMarker, content, scope, dashboardItemId } = data
                if (values.existingModalAnnotation) {
                    // annotationsModel's updateAnnotation inlined so that isAnnotationModalSubmitting works
                    const updatedAnnotation = await api.annotations.update(values.existingModalAnnotation.id, {
                        date_marker: dateMarker.toISOString(),
                        content,
                        scope,
                        dashboard_item: dashboardItemId,
                    })
                    actions.replaceAnnotation(updatedAnnotation)
                } else {
                    // annotationsModel's createAnnotationGenerically inlined so that isAnnotationModalSubmitting works
                    const createdAnnotation = await api.annotations.create({
                        date_marker: dateMarker.toISOString(),
                        content,
                        scope,
                        dashboard_item: dashboardItemId,
                    })
                    actions.appendAnnotations([createdAnnotation])
                }
                actions.closeModal()
            },
        },
    })),
])
