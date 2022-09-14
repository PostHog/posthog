import { Dayjs } from 'lib/dayjs'
import { kea, path, selectors, key, props, connect, listeners, actions, reducers } from 'kea'
import { groupBy } from 'lib/utils'
import { AnnotationScope, InsightModel, IntervalType } from '~/types'
import type { annotationsOverlayLogicType } from './annotationsOverlayLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AnnotationDataWithoutInsight, annotationsModel } from '~/models/annotationsModel'

export interface InsightAnnotationsLogicProps {
    dashboardItemId: InsightModel['short_id'] | 'new'
    insightNumericId: InsightModel['id'] | 'new'
}

/** Internal format for annotation groups. */
const INTERVAL_UNIT_TO_INTERNAL_DAYJS_FORMAT: Record<IntervalType, string> = {
    hour: 'YYYY-MM-DD HH',
    day: 'YYYY-MM-DD',
    week: 'YYYY-MM-DD',
    month: 'YYYY-MM',
}

export function determineAnnotationsDateGroup(date: Dayjs, intervalUnit: IntervalType): string {
    // FIXME: Account for ticks sometimes including more than one group in dense graphs
    return date.startOf(intervalUnit).format(INTERVAL_UNIT_TO_INTERNAL_DAYJS_FORMAT[intervalUnit])
}

export const annotationsOverlayLogic = kea<annotationsOverlayLogicType>([
    path((key) => ['lib', 'components', 'Annotations', 'annotationsOverlayLogic', key]),
    props({} as InsightAnnotationsLogicProps),
    key(({ insightNumericId }) => insightNumericId),
    connect({
        values: [
            insightLogic,
            ['intervalUnit', 'timezone', 'insightId'],
            annotationsModel,
            ['annotations', 'annotationsLoading'],
        ],
        actions: [annotationsModel, ['createAnnotationGenerically', 'updateAnnotation', 'deleteAnnotation']],
    }),
    actions({
        createAnnotation: (annotationData: AnnotationDataWithoutInsight) => ({ annotationData }),
        activateDate: (date: Dayjs, badgeElement: HTMLButtonElement) => ({ date, badgeElement }),
        deactivateDate: true,
        lockDate: true,
        unlockDate: true,
        closePopover: true,
    }),
    reducers({
        isPopoverShown: [
            false,
            {
                activateDate: () => true,
                deactivateDate: () => false,
                closePopover: () => false,
            },
        ],
        activeDate: [
            null as Dayjs | null,
            {
                activateDate: (_, { date }) => date,
            },
        ],
        activeBadgeElement: [
            null as HTMLButtonElement | null,
            {
                activateDate: (_, { badgeElement }) => badgeElement,
            },
        ],
        isDateLocked: [
            false,
            {
                lockDate: () => true,
                unlockDate: () => false,
                closePopover: () => false,
            },
        ],
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
                return groupBy(annotations, (annotation) => {
                    let datetime = annotation.date_marker.utc()
                    if (timezone !== 'UTC') {
                        datetime = datetime.tz(timezone) // If the target is non-UTC, perform conversion
                    }
                    return determineAnnotationsDateGroup(datetime, intervalUnit)
                })
            },
        ],
        popoverAnnotations: [
            (s) => [s.groupedAnnotations, s.activeDate, s.intervalUnit],
            (groupedAnnotations, activeDate, intervalUnit) => {
                return (activeDate && groupedAnnotations[determineAnnotationsDateGroup(activeDate, intervalUnit)]) || []
            },
        ],
    })),
])
