import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'

import '@posthog/lemon-ui'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { annotationsModel, deserializeAnnotation } from '~/models/annotationsModel'
import { AnnotationScope, AnnotationType, DashboardBasicType, QueryBasedInsightModel } from '~/types'

import type { annotationModalLogicType } from './annotationModalLogicType'

export const ANNOTATION_DAYJS_FORMAT = 'MMMM DD, YYYY h:mm A'

export const annotationScopeToName: Record<AnnotationScope, string> = {
    [AnnotationScope.Insight]: 'Insight',
    [AnnotationScope.Dashboard]: 'Dashboard',
    [AnnotationScope.Project]: 'Project',
    [AnnotationScope.Organization]: 'Organization',
}

export const annotationScopeToLevel: Record<AnnotationScope, number> = {
    [AnnotationScope.Insight]: 0,
    [AnnotationScope.Dashboard]: 1,
    [AnnotationScope.Project]: 2,
    [AnnotationScope.Organization]: 3,
}

export interface AnnotationModalForm {
    dateMarker: Dayjs
    scope: AnnotationType['scope']
    content: AnnotationType['content']
    dashboardItemId: AnnotationType['dashboard_item'] | null
    dashboardId: AnnotationType['dashboard_id'] | null
}

export const annotationModalLogic = kea<annotationModalLogicType>([
    path(['scenes', 'annotations', 'annotationModalLogic']),
    connect(() => ({
        actions: [
            annotationsModel,
            ['loadAnnotationsSuccess', 'replaceAnnotation', 'appendAnnotations', 'deleteAnnotation'],
        ],
        values: [annotationsModel, ['annotations', 'annotationsLoading'], teamLogic, ['timezone'], userLogic, ['user']],
    })),
    actions({
        openModalToCreateAnnotation: (
            initialDate?: Dayjs | null,
            insightId?: QueryBasedInsightModel['id'] | null,
            dashboardId?: DashboardBasicType['id'] | null
        ) => ({
            initialDate,
            insightId,
            dashboardId,
        }),
        openModalToEditAnnotation: (
            annotation: AnnotationType,
            insightId?: QueryBasedInsightModel['id'] | null,
            dashboardId?: DashboardBasicType['id'] | null
        ) => ({
            annotation,
            insightId,
            dashboardId,
        }),
        closeModal: true,
        setScope: (scope: AnnotationType['scope'] | null) => ({ scope }),
    }),
    reducers(() => ({
        scope: [null as AnnotationType['scope'] | null, { setScope: (_, { scope }) => scope }],
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
    listeners(({ cache, actions, values }) => ({
        openModalToEditAnnotation: ({ annotation: { date_marker, scope, content }, insightId, dashboardId }) => {
            actions.setAnnotationModalValues({
                dateMarker: dayjs(date_marker).tz(values.timezone),
                scope,
                content,
            })
            if (insightId) {
                actions.setAnnotationModalValue('dashboardItemId', insightId)
            }
            if (dashboardId) {
                actions.setAnnotationModalValue('dashboardId', dashboardId)
            }
        },
        openModalToCreateAnnotation: ({ initialDate, insightId, dashboardId }) => {
            actions.resetAnnotationModal()
            if (initialDate) {
                actions.setAnnotationModalValue('dateMarker', initialDate)
            }
            if (insightId) {
                actions.setAnnotationModalValue('dashboardItemId', insightId)
            }
            if (dashboardId) {
                actions.setAnnotationModalValue('dashboardId', dashboardId)
            }
        },
        loadAnnotationsSuccess: ({ rawAnnotations }) => {
            if (!values.isModalOpen && cache.annotationToShowId) {
                const annotation = rawAnnotations.find((a) => a.id === cache.annotationToShowId)
                if (!annotation) {
                    return // If the annotation isn't there by now, then we're lost
                }
                actions.openModalToEditAnnotation(deserializeAnnotation(annotation, teamLogic.values.timezone))
                delete cache.annotationToShowId
            }
        },
    })),
    selectors(() => ({
        shouldShowEmptyState: [
            (s) => [s.annotations, s.annotationsLoading],
            (annotations, annotationsLoading): boolean => {
                return annotations.length === 0 && !annotationsLoading
            },
        ],
    })),
    forms(({ actions, values }) => ({
        annotationModal: {
            defaults: {
                dateMarker: dayjs().tz(values.timezone),
                content: '',
                scope: AnnotationScope.Project,
                dashboardItemId: null,
                dashboardId: null,
            } as AnnotationModalForm,
            errors: ({ content }) => ({
                content: !content?.trim() ? 'An annotation must have text content.' : null,
            }),
            submit: async (data) => {
                const { dateMarker, content, scope, dashboardItemId, dashboardId } = data

                if (values.existingModalAnnotation) {
                    // annotationsModel's updateAnnotation inlined so that isAnnotationModalSubmitting works
                    const updatedAnnotation = await api.annotations.update(values.existingModalAnnotation.id, {
                        date_marker: dateMarker.toISOString(),
                        content,
                        scope,
                        // update to new insight we're saving from
                        dashboard_item: dashboardItemId,
                        // preserve existing dashboard id
                        dashboard_id: values.existingModalAnnotation.dashboard_id,
                    })
                    actions.replaceAnnotation(updatedAnnotation)
                } else {
                    // annotationsModel's createAnnotationGenerically inlined so that isAnnotationModalSubmitting works
                    const createdAnnotation = await api.annotations.create({
                        date_marker: dateMarker.toISOString(),
                        content,
                        scope,
                        dashboard_item: dashboardItemId,
                        dashboard_id: dashboardId,
                    })
                    actions.appendAnnotations([createdAnnotation])
                }
                actions.closeModal()
            },
        },
    })),
    urlToAction(({ values, actions, cache }) => ({
        [urls.annotation(':id')]: ({ id }) => {
            cache.annotationToShowId = parseInt(id as string)
            const annotation = values.annotations.find((a) => a.id === cache.annotationToShowId)
            if (!annotation) {
                return // This means there are no annotations yet, so we'll open the modal in loadAnnotationsSuccess
            }
            actions.openModalToEditAnnotation(annotation)
        },
    })),
])
