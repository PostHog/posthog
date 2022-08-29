import { dayjs } from 'lib/dayjs'
import { kea, path, selectors, key, props, connect, listeners, actions } from 'kea'
import { groupBy } from 'lib/utils'
import { AnnotationScope, InsightModel } from '~/types'
import type { insightAnnotationsLogicType } from './insightAnnotationsLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AnnotationData, annotationsLogic } from 'scenes/annotations/annotationsLogic'

interface InsightAnnotationsLogicProps {
    dashboardItemId: InsightModel['short_id']
    insightNumericId: InsightModel['id'] | 'new'
}

export const insightAnnotationsLogic = kea<insightAnnotationsLogicType>([
    path((key) => ['lib', 'components', 'Annotations', 'insightAnnotationsLogic', key]),
    props({} as InsightAnnotationsLogicProps),
    key(({ insightNumericId }) => insightNumericId),
    connect({
        values: [insightLogic, ['intervalUnit'], annotationsLogic, ['annotations', 'annotationsLoading']],
        actions: [annotationsLogic, ['createAnnotationGenerically', 'updateAnnotation', 'deleteAnnotation']],
    }),
    actions({
        createAnnotation: (annotationData: Omit<AnnotationData, 'insightId'>) => ({ annotationData }),
    }),
    listeners(({ actions, props }) => ({
        createAnnotation: async ({ annotationData }) => {
            actions.createAnnotationGenerically({ ...annotationData, dashboard_item: props.insightNumericId })
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
            (s) => [s.relevantAnnotations, s.intervalUnit],
            (annotations, intervalUnit) => {
                return groupBy(annotations, (annotation) =>
                    dayjs(annotation['date_marker']).startOf(intervalUnit).format('YYYY-MM-DD')
                )
            },
        ],
    })),
])
