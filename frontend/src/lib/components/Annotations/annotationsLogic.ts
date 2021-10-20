import { kea } from 'kea'
import api from 'lib/api'
import dayjs, { Dayjs, OpUnitType } from 'dayjs'
import { deleteWithUndo, determineDifferenceType, groupBy, toParams } from '~/lib/utils'
import { annotationsModel } from '~/models/annotationsModel'
import { getNextKey } from './utils'
import { annotationsLogicType } from './annotationsLogicType'
import { AnnotationScope, AnnotationType } from '~/types'
import { teamLogic } from '../../../scenes/teamLogic'

interface AnnotationsLogicProps {
    pageKey?: string | number | null
}

export const annotationsLogic = kea<annotationsLogicType<AnnotationsLogicProps>>({
    props: {} as AnnotationsLogicProps,
    key: (props) => (props.pageKey ? `${props.pageKey}_annotations` : 'annotations_default'),
    connect: {
        actions: [annotationsModel, ['deleteGlobalAnnotation', 'createGlobalAnnotation']],
        values: [annotationsModel, ['activeGlobalAnnotations']],
    },
    actions: () => ({
        createAnnotation: (
            content: string,
            date_marker: string,
            scope: AnnotationScope = AnnotationScope.DashboardItem
        ) => ({
            content,
            date_marker,
            created_at: dayjs(),
            scope,
        }),
        createAnnotationNow: (
            content: string,
            date_marker: string,
            scope: AnnotationScope = AnnotationScope.DashboardItem
        ) => ({
            content,
            date_marker,
            created_at: dayjs() as Dayjs,
            scope,
        }),
        deleteAnnotation: (id: string) => ({ id }),
        clearAnnotationsToCreate: true,
        updateDiffType: (dates: string[]) => ({ dates }),
        setDiffType: (type: OpUnitType) => ({ type }),
    }),
    loaders: ({ props }) => ({
        annotations: {
            __default: [] as AnnotationType[],
            loadAnnotations: async () => {
                const params = {
                    ...(props.pageKey ? { dashboardItemId: props.pageKey } : {}),
                    scope: AnnotationScope.DashboardItem,
                    deleted: false,
                }
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/annotations/?${toParams(params)}`
                )
                return response.results
            },
        },
    }),
    reducers: {
        annotations: {
            createAnnotationNow: (state, { content, date_marker, created_at, scope }) => [
                ...state,
                {
                    id: getNextKey(state).toString(),
                    content,
                    date_marker: date_marker,
                    created_at: created_at.toISOString(),
                    updated_at: created_at.toISOString(),
                    created_by: 'local',
                    scope,
                },
            ],
            deleteAnnotation: (state, { id }) => {
                if (parseInt(id) >= 0) {
                    return state.filter((a) => a.id !== id)
                } else {
                    return state
                }
            },
        },

        annotationsToCreate: [
            [] as AnnotationType[],
            {
                createAnnotation: (state, { content, date_marker, created_at, scope }) => [
                    ...state,
                    {
                        id: getNextKey(state).toString(),
                        content,
                        date_marker: date_marker,
                        created_at: created_at.toISOString(),
                        updated_at: created_at.toISOString(),
                        created_by: 'local',
                        scope,
                    },
                ],
                clearAnnotationsToCreate: () => [],
                deleteAnnotation: (state, { id }) => {
                    if (parseInt(id) < 0) {
                        return state.filter((a) => a.id !== id)
                    } else {
                        return state
                    }
                },
            },
        ],
        diffType: [
            'day' as string,
            {
                setDiffType: (_, { type }) => type,
            },
        ],
    },
    selectors: ({ selectors }) => ({
        annotationsList: [
            () => [selectors.annotationsToCreate, selectors.annotations, selectors.activeGlobalAnnotations],
            (annotationsToCreate, annotations, activeGlobalAnnotations) =>
                [...annotationsToCreate, ...annotations, ...activeGlobalAnnotations] as AnnotationType[],
        ],
        groupedAnnotations: [
            () => [selectors.annotationsList, selectors.diffType],
            (annotationsList, diffType) =>
                groupBy(annotationsList, (annotation) =>
                    dayjs(annotation['date_marker'])
                        .startOf(diffType as OpUnitType)
                        .format('YYYY-MM-DD')
                ),
        ],
    }),
    listeners: ({ actions, props }) => ({
        createAnnotationNow: async ({ content, date_marker, created_at, scope }) => {
            await api.create(`api/projects/${teamLogic.values.currentTeamId}/annotations`, {
                content,
                date_marker: dayjs(date_marker),
                created_at,
                dashboard_item: props.pageKey,
                scope,
            })
            actions.loadAnnotations()
        },
        deleteAnnotation: async ({ id }) => {
            parseInt(id) >= 0 &&
                deleteWithUndo({
                    endpoint: `projects/${teamLogic.values.currentTeamId}/annotations`,
                    object: { name: 'Annotation', id },
                    callback: () => actions.loadAnnotations(),
                })
        },
        updateDiffType: ({ dates }) => {
            actions.setDiffType(determineDifferenceType(dates[0], dates[1]))
        },
    }),
    events: ({ actions, props }) => ({
        afterMount: () => props.pageKey && actions.loadAnnotations(),
    }),
})
