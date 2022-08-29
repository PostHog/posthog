import { dayjs } from 'lib/dayjs'
import { kea, path, selectors, key, props, connect, listeners, actions } from 'kea'
import { groupBy } from 'lib/utils'
import { AnnotationScope, InsightModel, IntervalType } from '~/types'
import type { insightAnnotationsLogicType } from './insightAnnotationsLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AnnotationDataWithoutInsight, annotationsModel } from '~/models/annotationsModel'

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
        values: [insightLogic, ['intervalUnit', 'timezone'], annotationsModel, ['annotations', 'annotationsLoading']],
        actions: [annotationsModel, ['createAnnotationGenerically', 'updateAnnotation', 'deleteAnnotation']],
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
                // This assumes that there are no more than AnnotationsViewSet.default_limit (500) annotations
                // in the project. Right now this is true on Cloud, though some projects are getting close (400+).
                // If we see the scale increasing, we might need to fetch annotations on a per-insight basis here.
                // That would greatly increase the number of requests to the annotations endpoint though.
                return annotations.filter(
                    (annotation) =>
                        annotation.scope !== AnnotationScope.Insight ||
                        annotation.dashboard_item === props.insightNumericId
                )
            },
        ],
        groupedAnnotations: [
            (s) => [s.relevantAnnotations, s.intervalUnit, s.timezone],
            (annotations, intervalUnit, timezone) => {
                const format = INTERVAL_UNIT_TO_DAYJS_FORMAT[intervalUnit]
                return groupBy(annotations, (annotation) =>
                    dayjs.utc(annotation['date_marker']).tz(timezone, true).startOf(intervalUnit).format(format)
                )
            },
        ],
    })),
])
