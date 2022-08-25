import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import { annotationsModel } from '~/models/annotationsModel'
import type { annotationsPageLogicType } from './logicType'
import { AnnotationScope, AnnotationType } from '~/types'
import { teamLogic } from '../teamLogic'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { dayjs, Dayjs } from 'lib/dayjs'

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
    dateMarker: Dayjs
    scope: AnnotationType['scope']
    content: AnnotationType['content']
}

export const annotationsPageLogic = kea<annotationsPageLogicType>([
    path(['scenes', 'annotations', 'logic']),
    actions(() => ({
        updateAnnotation: (id, content) => ({ id, content }),
        deleteAnnotation: (id) => ({ id }),
        restoreAnnotation: (id) => ({ id }),
        loadAnnotationsNext: () => true,
        setNext: (next) => ({ next }),
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
        modalAnnotation: [
            null as AnnotationType | null,
            {
                openModalToCreateAnnotation: () => null,
                openModalToEditAnnotation: (_, { annotation }) => annotation,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        updateAnnotation: async ({ id, content }) => {
            await api.update(`api/projects/${teamLogic.values.currentTeamId}/annotations/${id}`, { content })
            actions.loadAnnotations()
        },
        restoreAnnotation: async ({ id }) => {
            await api.update(`api/projects/${teamLogic.values.currentTeamId}/annotations/${id}`, { deleted: false })
            actions.loadAnnotations()
        },
        deleteAnnotation: ({ id }) => {
            deleteWithUndo({
                endpoint: `projects/${teamLogic.values.currentTeamId}/annotations`,
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
    forms(({ actions }) => ({
        annotationModal: {
            defaults: {
                dateMarker: dayjs(),
                content: '',
                scope: AnnotationScope.Project,
            },
            errors: ({ content }) => ({
                content: !content ? 'An annotation must have text content.' : null,
            }),
            submit: async (data) => {
                const { dateMarker, content, scope } = data
                await api.annotations.create({
                    date_marker: dateMarker.toISOString(),
                    content,
                    scope,
                })
                actions.closeModal()
            },
        },
    })),
])
