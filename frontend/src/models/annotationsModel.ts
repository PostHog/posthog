import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import { now, dayjs } from 'lib/dayjs'
import { getNextKey } from 'lib/components/Annotations/utils'
import type { annotationsModelType } from './annotationsModelType'
import { AnnotationScope, AnnotationType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

export const annotationsModel = kea<annotationsModelType>({
    path: ['models', 'annotationsModel'],
    actions: {
        createGlobalAnnotation: (content: string, date_marker: string, insightNumericId?: number) => ({
            content,
            date_marker,
            created_at: now(),
            created_by: userLogic.values.user,
            insightNumericId,
        }),
        deleteGlobalAnnotation: (id) => ({ id }),
    },
    loaders: ({ values }) => ({
        globalAnnotations: {
            __default: [] as AnnotationType[],
            loadGlobalAnnotations: async () => {
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/annotations/?${toParams({
                        scope: 'organization',
                        deleted: false,
                    })}`
                )
                return response.results
            },
            createGlobalAnnotation: async ({ insightNumericId, content, date_marker, created_at }) => {
                await api.create(`api/projects/${teamLogic.values.currentTeamId}/annotations`, {
                    content,
                    date_marker: (dayjs.isDayjs(date_marker) ? date_marker : dayjs(date_marker)).toISOString(),
                    created_at: created_at.toISOString(),
                    dashboard_item: insightNumericId,
                    scope: AnnotationScope.Organization,
                } as Partial<AnnotationType>)
                return values.globalAnnotations || []
            },
        },
    }),
    reducers: {
        globalAnnotations: {
            createGlobalAnnotation: (state, { content, date_marker, created_at, created_by }) => [
                ...state,
                {
                    id: getNextKey(state).toString(),
                    content,
                    date_marker: date_marker,
                    created_at: created_at.toISOString(),
                    updated_at: created_at.toISOString(),
                    created_by,
                    scope: AnnotationScope.Organization,
                } as AnnotationType,
            ],
            deleteGlobalAnnotation: (state, { id }) => {
                return state.filter((a) => a.id !== id)
            },
        },
    },
    selectors: {
        activeGlobalAnnotations: [
            (s) => [s.globalAnnotations],
            (globalAnnotations) => {
                return globalAnnotations.filter((annotation) => !annotation.deleted)
            },
        ],
    },
    listeners: ({ actions }) => ({
        deleteGlobalAnnotation: ({ id }) => {
            id >= 0 &&
                deleteWithUndo({
                    endpoint: `projects/${teamLogic.values.currentTeamId}/annotations`,
                    object: { name: 'Annotation', id },
                    callback: () => actions.loadGlobalAnnotations(),
                })
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => actions.loadGlobalAnnotations(),
    }),
})
