import { dayjs } from 'lib/dayjs'
import { kea, path, selectors, key, props, connect, listeners, actions } from 'kea'
import { groupBy } from 'lib/utils'
import { AnnotationScope, InsightModel, IntervalType } from '~/types'
import type { insightAnnotationsLogicType } from './insightAnnotationsLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AnnotationDataWithoutInsight, annotationsLogic } from 'scenes/annotations/annotationsLogic'
import { teamLogic } from 'scenes/teamLogic'

export interface InsightAnnotationsLogicProps {
    dashboardItemId: InsightModel['short_id'] | 'new'
    insightNumericId: InsightModel['id'] | 'new'
}

const INTERVAL_UNIT_TO_DAYJS_FORMAT: Record<IntervalType, string> = {
    hour: 'YYYY-MM-DD HH',
    day: 'YYYY-MM-DD',
    week: 'YYYY-MM-DD',
    month: 'YYYY-MM',
}

export const insightAnnotationsLogic = kea<insightAnnotationsLogicType>([
    path((key) => ['lib', 'components', 'Annotations', 'insightAnnotationsLogic', key]),
    props({} as InsightAnnotationsLogicProps),
    key(({ insightNumericId }) => insightNumericId),
    connect({
        values: [
            insightLogic,
            ['intervalUnit'],
            annotationsLogic,
            ['annotations', 'annotationsLoading'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [annotationsLogic, ['createAnnotationGenerically', 'updateAnnotation', 'deleteAnnotation']],
    }),
    actions({
        createAnnotation: (annotationData: AnnotationDataWithoutInsight) => ({ annotationData }),
    }),
    listeners(({ actions, props }) => ({
        createAnnotation: async ({ annotationData }) => {
            const insightNumericId = props.insightNumericId !== 'new' ? props.insightNumericId : null
            actions.createAnnotationGenerically({ ...annotationData, dashboard_item: insightNumericId })
        },
    })),
    selectors(({ props }) => ({
        relevantAnnotations: [
            (s) => [s.annotations],
            (annotations) => {
                return annotations.filter(
                    (annotation) =>
                        annotation.scope !== AnnotationScope.Insight ||
                        annotation.dashboard_item === props.insightNumericId
                )
            },
        ],
        groupedAnnotations: [
            (s) => [s.relevantAnnotations, s.intervalUnit, s.currentTeam],
            (annotations, intervalUnit, currentTeam) => {
                const format = INTERVAL_UNIT_TO_DAYJS_FORMAT[intervalUnit]
                return groupBy(annotations, (annotation) =>
                    dayjs
                        .utc(annotation['date_marker'])
                        .tz(currentTeam?.timezone || 'UTC', true)
                        .startOf(intervalUnit)
                        .format(format)
                )
            },
        ],
    })),
])
