import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import dayjs, { Dayjs } from 'dayjs'
import { getNextKey } from 'lib/components/Annotations/utils'
import { annotationsModelType } from './annotationsModelType'
import { AnnotationScope, AnnotationType } from '~/types'
import { ProjectBasedLogicProps, getProjectBasedLogicKeyBuilder } from 'lib/utils/logics'

export const annotationsModel = kea<annotationsModelType>({
    props: {} as ProjectBasedLogicProps,
    key: getProjectBasedLogicKeyBuilder(),
    actions: {
        createGlobalAnnotation: (content: string, date_marker: string, dashboard_item?: number) => ({
            content,
            date_marker,
            created_at: dayjs() as Dayjs,
            dashboard_item,
        }),
        deleteGlobalAnnotation: (id) => ({ id }),
    },
    loaders: ({ values, props }) => ({
        globalAnnotations: {
            __default: [] as AnnotationType[],
            loadGlobalAnnotations: async () => {
                const response = await api.get(
                    `api/projects/${props.teamId}/annotations/?${toParams({
                        scope: 'organization',
                        deleted: false,
                    })}`
                )
                return response.results
            },
            createGlobalAnnotation: async ({ dashboard_item, content, date_marker, created_at }) => {
                await api.create(`api/projects/${props.teamId}/annotations`, {
                    content,
                    date_marker: dayjs.isDayjs(date_marker) ? date_marker : dayjs(date_marker),
                    created_at,
                    dashboard_item,
                    scope: AnnotationScope.Organization,
                })
                return values.globalAnnotations || []
            },
        },
    }),
    reducers: {
        globalAnnotations: {
            createGlobalAnnotation: (state, { content, date_marker, created_at }) => [
                ...state,
                {
                    id: getNextKey(state).toString(),
                    content,
                    date_marker: date_marker,
                    created_at: created_at.toISOString(),
                    updated_at: created_at.toISOString(),
                    created_by: 'local',
                    scope: AnnotationScope.Organization,
                },
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
    listeners: ({ actions, props }) => ({
        deleteGlobalAnnotation: ({ id }) => {
            id >= 0 &&
                deleteWithUndo({
                    endpoint: `projects/${props.teamId}/annotations`,
                    object: { name: 'Annotation', id },
                    callback: () => actions.loadGlobalAnnotations(),
                })
        },
    }),
    events: ({ actions, props }) => ({
        afterMount: () => props.teamId && actions.loadGlobalAnnotations(),
    }),
})
