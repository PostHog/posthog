import { kea } from 'kea'
import api from 'lib/api'
import { dayjs, now, OpUnitType } from 'lib/dayjs'
import { deleteWithUndo, determineDifferenceType, groupBy, toParams } from '~/lib/utils'
import { annotationsModel } from '~/models/annotationsModel'
import { getNextKey } from './utils'
import type { annotationsLogicType } from './annotationsLogicType'
import { AnnotationScope, AnnotationType } from '~/types'
import { teamLogic } from 'scenes/teamLogic'

export interface AnnotationsLogicProps {
    insightNumericId?: number
}

export const annotationsLogic = kea<annotationsLogicType>({
    path: (key) => ['lib', 'components', 'Annotations', 'annotationsLogic', key],
    props: {} as AnnotationsLogicProps,
    key: (props) => String(props.insightNumericId || 'default'),
    connect: {
        actions: [annotationsModel, ['deleteGlobalAnnotation', 'createGlobalAnnotation']],
        values: [annotationsModel, ['activeGlobalAnnotations']],
    },
    actions: () => ({
        createAnnotation: (content: string, date_marker: string, scope: AnnotationScope = AnnotationScope.Insight) => ({
            content,
            date_marker,
            created_at: now(),
            scope,
        }),
        deleteAnnotation: (id: string) => ({ id }),
        updateDiffType: (dates: string[]) => ({ dates }),
        setDiffType: (type: OpUnitType) => ({ type }),
    }),
    loaders: ({ props }) => ({
        annotations: {
            __default: [] as AnnotationType[],
            loadAnnotations: async () => {
                if (!props.insightNumericId) {
                    // insight.id (numeric ID) not known yet
                    return []
                }

                const params = {
                    ...(props.insightNumericId ? { dashboardItemId: props.insightNumericId } : {}),
                    scope: AnnotationScope.Insight,
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
            createAnnotation: (state, { content, date_marker, created_at, scope }) => [
                ...state,
                {
                    id: getNextKey(state).toString(),
                    content,
                    date_marker: date_marker,
                    created_at: created_at.toISOString(),
                    updated_at: created_at.toISOString(),
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
        diffType: [
            'day' as string,
            {
                setDiffType: (_, { type }) => type,
            },
        ],
    },
    selectors: ({ selectors }) => ({
        annotationsList: [
            () => [selectors.annotations, selectors.activeGlobalAnnotations],
            (annotations, activeGlobalAnnotations): AnnotationType[] => [...annotations, ...activeGlobalAnnotations],
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
        createAnnotation: async ({ content, date_marker, created_at, scope }) => {
            if (!props.insightNumericId) {
                throw new Error('Can only create annotations for insights whose id is known.')
            }

            await api.create(`api/projects/${teamLogic.values.currentTeamId}/annotations`, {
                content,
                date_marker: dayjs(date_marker).toISOString(),
                created_at: created_at.toISOString(),
                dashboard_item: props.insightNumericId,
                scope,
            } as Partial<AnnotationType>)
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
    events: ({ actions }) => ({
        afterMount: () => actions.loadAnnotations(),
    }),
})
