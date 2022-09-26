import { Dayjs, dayjsLocalToTimezone } from 'lib/dayjs'
import { kea, path, selectors, key, props, connect, listeners, actions, reducers } from 'kea'
import { groupBy } from 'lib/utils'
import { AnnotationScope, InsightLogicProps, InsightModel, IntervalType } from '~/types'
import type { annotationsOverlayLogicType } from './annotationsOverlayLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AnnotationDataWithoutInsight, annotationsModel } from '~/models/annotationsModel'
import { teamLogic } from 'scenes/teamLogic'
import { Tick } from 'chart.js'

export interface AnnotationsOverlayLogicProps {
    dashboardItemId: InsightLogicProps['dashboardItemId']
    insightNumericId: InsightModel['id'] | 'new'
    dates: string[]
    ticks: Tick[]
}

export function determineAnnotationsDateGroup(
    date: Dayjs,
    intervalUnit: IntervalType,
    dateRange: [Dayjs, Dayjs] | null,
    pointsPerTick: number
): string {
    let adjustedDate = date.startOf(intervalUnit)
    if (dateRange && pointsPerTick > 1) {
        // Merge dates that are within the same tick (this is the case for very dense graphs with not enough space)
        const deltaFromStart = date.diff(dateRange[0], intervalUnit)
        const offset = deltaFromStart % pointsPerTick
        adjustedDate = adjustedDate.subtract(offset, intervalUnit)
    }
    return adjustedDate.format('YYYY-MM-DD HH:mm:ssZZ')
}

export const annotationsOverlayLogic = kea<annotationsOverlayLogicType>([
    path((key) => ['lib', 'components', 'Annotations', 'annotationsOverlayLogic', key]),
    props({} as AnnotationsOverlayLogicProps),
    key(({ insightNumericId }) => insightNumericId),
    connect(() => ({
        values: [
            insightLogic,
            ['intervalUnit', 'insightId'],
            annotationsModel,
            ['annotations', 'annotationsLoading'],
            teamLogic,
            ['timezone'],
        ],
        actions: [annotationsModel, ['createAnnotationGenerically', 'updateAnnotation', 'deleteAnnotation']],
    })),
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
        pointsPerTick: [
            () => [(_, props) => props.ticks],
            (ticks): number => {
                if (ticks.length < 2) {
                    return 0
                }
                return ticks[1].value - ticks[0].value
            },
        ],
        tickDates: [
            (s) => [s.timezone, (_, props) => props.dates, (_, props) => props.ticks],
            (timezone, dates, ticks): Dayjs[] => {
                const tickPointIndices: number[] = ticks.map(({ value }) => value)
                const tickDates: Dayjs[] = tickPointIndices.map((dateIndex) =>
                    dayjsLocalToTimezone(dates[dateIndex], timezone)
                )
                return tickDates
            },
        ],
        dateRange: [
            (s) => [s.tickDates, s.intervalUnit, s.pointsPerTick],
            (tickDates, intervalUnit, pointsPerTick): [Dayjs, Dayjs] | null => {
                if (tickDates.length === 0) {
                    return null
                }
                return [tickDates[0], tickDates[tickDates.length - 1].add(pointsPerTick, intervalUnit)]
            },
        ],
        relevantAnnotations: [
            (s) => [s.annotations, s.dateRange],
            (annotations, dateRange) => {
                // This assumes that there are no more than AnnotationsViewSet.default_limit (500) annotations
                // in the project. Right now this is true on Cloud, though some projects are getting close (400+).
                // If we see the scale increasing, we might need to fetch annotations on a per-insight basis here.
                // That would greatly increase the number of requests to the annotations endpoint though.
                return dateRange
                    ? annotations.filter(
                          (annotation) =>
                              (annotation.scope !== AnnotationScope.Insight ||
                                  annotation.dashboard_item === props.insightNumericId) &&
                              annotation.date_marker >= dateRange[0] &&
                              annotation.date_marker < dateRange[1]
                      )
                    : []
            },
        ],
        groupedAnnotations: [
            (s) => [s.relevantAnnotations, s.intervalUnit, s.dateRange, s.pointsPerTick],
            (relevantAnnotations, intervalUnit, dateRange, pointsPerTick) => {
                return groupBy(relevantAnnotations, (annotation) => {
                    return determineAnnotationsDateGroup(annotation.date_marker, intervalUnit, dateRange, pointsPerTick)
                })
            },
        ],
        popoverAnnotations: [
            (s) => [s.groupedAnnotations, s.activeDate, s.intervalUnit, s.dateRange, s.pointsPerTick],
            (groupedAnnotations, activeDate, intervalUnit, dateRange, pointsPerTick) => {
                return (
                    (activeDate &&
                        groupedAnnotations[
                            determineAnnotationsDateGroup(activeDate, intervalUnit, dateRange, pointsPerTick)
                        ]) ||
                    []
                )
            },
        ],
    })),
])
