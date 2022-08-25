import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import { annotationsModel } from '~/models/annotationsModel'
import type { annotationsPageLogicType } from './annotationsPageLogicType'
import { AnnotationScope, AnnotationType } from '~/types'
import { teamLogic } from '../teamLogic'
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

export type AnnotationModalForm = {
    dateMarker: dayjs.Dayjs
    scope: AnnotationType['scope']
    content: AnnotationType['content']
}

export const annotationsPageLogic = kea<annotationsPageLogicType>([
    path(['scenes', 'annotations', 'logic']),
    actions(() => ({
        deleteAnnotation: (id: AnnotationType['id']) => ({ id }),
        restoreAnnotation: (id: AnnotationType['id']) => ({ id }),
        loadAnnotationsNext: () => true,
        setNext: (next: string) => ({ next }),
        appendAnnotations: (annotations: AnnotationType[]) => ({ annotations }),
        openModalToCreateAnnotation: () => true,
        openModalToEditAnnotation: (annotation: AnnotationType) => ({ annotation }),
        closeModal: true,
    })),
    loaders(({ actions }) => ({
        annotations: {
            __default: [],
            loadAnnotations: async () => {
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/annotations/?${toParams({ order: '-updated_at' })}`
                )
                actions.setNext(response.next)
                return response.results
            },
        },
    })),
    reducers(() => ({
        annotations: [
            [] as AnnotationType[],
            {
                appendAnnotations: (state, { annotations }) => [...state, ...annotations],
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
        restoreAnnotation: async ({ id }) => {
            await api.annotations.restore(id)
            actions.loadAnnotations()
        },
        deleteAnnotation: ({ id }) => {
            deleteWithUndo({
                endpoint: api.annotations.determineDeleteEndpoint(),
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
        [annotationsModel.actionTypes.createGlobalAnnotationSuccess]: () => {
            actions.loadAnnotations()
        },
    })),
    afterMount(({ actions }) => actions.loadAnnotations()),
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
                    await api.annotations.update(values.existingModalAnnotation.id, {
                        date_marker: dateMarker.toISOString(),
                        content,
                        scope,
                    })
                } else {
                    await api.annotations.create({
                        date_marker: dateMarker.toISOString(),
                        content,
                        scope,
                    })
                }
                actions.loadAnnotations()
                actions.closeModal()
            },
        },
    })),
])
