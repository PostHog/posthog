import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { annotationsModel, deserializeAnnotation } from '~/models/annotationsModel'
import { AnnotationScope, AnnotationType, InsightModel, ProductKey } from '~/types'

import type { annotationModalLogicType } from './annotationModalLogicType'

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
            [
                'loadAnnotationsNext',
                'loadAnnotationsSuccess',
                'replaceAnnotation',
                'appendAnnotations',
                'deleteAnnotation',
            ],
        ],
        values: [
            annotationsModel,
            ['annotations', 'annotationsLoading', 'next', 'loadingNext'],
            teamLogic,
            ['timezone'],
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
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
    listeners(({ cache, actions, values }) => ({
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
                actions.setAnnotationModalValue('dashboardItemId', insightId)
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
        shouldShowProductIntroduction: [
            (s) => [s.user, s.featureFlags],
            (user, featureFlags): boolean => {
                return (
                    !user?.has_seen_product_intro_for?.[ProductKey.ANNOTATIONS] &&
                    !!featureFlags[FEATURE_FLAGS.SHOW_PRODUCT_INTRO_EXISTING_PRODUCTS]
                )
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
            } as AnnotationModalForm,
            errors: ({ content }) => ({
                content: !content?.trim() ? 'An annotation must have text content.' : null,
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
