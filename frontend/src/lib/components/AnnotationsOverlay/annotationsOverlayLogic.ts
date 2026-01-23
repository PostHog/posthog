import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { isPersonPropertyFilter, parseProperties } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs, dayjsLocalToTimezone } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { groupBy } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AnnotationDataWithoutInsight, annotationsModel } from '~/models/annotationsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import {
    AnnotationScope,
    AnnotationType,
    AnyPropertyFilter,
    DashboardType,
    DatedAnnotationType,
    InsightLogicProps,
    IntervalType,
    PropertyGroupFilter,
    QueryBasedInsightModel,
} from '~/types'

import type { annotationsOverlayLogicType } from './annotationsOverlayLogicType'

export interface AnnotationsOverlayLogicProps extends Omit<InsightLogicProps, 'dashboardId'> {
    dashboardId: DashboardType['id'] | undefined
    insightNumericId: QueryBasedInsightModel['id'] | 'new'
    dates: string[]
    ticks: { value: number }[]
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

function hasPersonPropertyFiltersOrBreakdown(
    properties: AnyPropertyFilter[] | PropertyGroupFilter | null | undefined,
    breakdownFilter: BreakdownFilter | null | undefined
): boolean {
    // Check if there are person property filters
    if (properties) {
        const parsedProperties = parseProperties(properties)
        if (parsedProperties.some((prop) => isPersonPropertyFilter(prop))) {
            return true
        }
    }

    // Check if breakdown is by person property
    if (breakdownFilter) {
        if (breakdownFilter.breakdown_type === 'person') {
            return true
        }
        if (breakdownFilter.breakdowns?.some((breakdown) => breakdown.type === 'person')) {
            return true
        }
    }

    return false
}

export const annotationsOverlayLogic = kea<annotationsOverlayLogicType>([
    path((key) => ['lib', 'components', 'Annotations', 'annotationsOverlayLogic', key]),
    props({ dashboardId: undefined } as AnnotationsOverlayLogicProps),
    key(({ insightNumericId }) => insightNumericId),
    connect(() => ({
        values: [
            insightLogic,
            ['insightId', 'savedInsight'],
            insightVizDataLogic,
            ['interval', 'properties', 'breakdownFilter'],
            annotationsModel,
            ['annotations', 'annotationsLoading'],
            teamLogic,
            ['timezone'],
            featureFlagLogic,
            ['featureFlags'],
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
                deactivateDate: () => null,
                closePopover: () => null,
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
    selectors({
        annotationsOverlayProps: [
            () => [(_, props) => props],
            (props: AnnotationsOverlayLogicProps): AnnotationsOverlayLogicProps => props,
        ],
        intervalUnit: [(s) => [s.interval], (interval) => interval || 'day'],
        pointsPerTick: [
            (_, p) => [p.ticks],
            (ticks): number => {
                if (ticks.length < 2) {
                    return 0
                }
                return ticks[1].value - ticks[0].value
            },
        ],
        tickDates: [
            (s) => [
                s.timezone,
                (_, props: AnnotationsOverlayLogicProps) => props.dates,
                (_, props: AnnotationsOverlayLogicProps) => props.ticks,
            ],
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
            (s, p) => [
                s.annotations,
                s.dateRange,
                s.timezone,
                s.featureFlags,
                p.insightNumericId,
                p.dashboardId,
                s.savedInsight,
                s.properties,
                s.breakdownFilter,
            ],
            (
                annotations,
                dateRange,
                timezone,
                featureFlags,
                insightNumericId,
                dashboardId,
                savedInsight,
                properties,
                breakdownFilter
            ) => {
                // This assumes that there are no more annotations in the project than AnnotationsViewSet
                // pagination class's default_limit of 100. As of June 2023, this is not true on Cloud US,
                // where 3 projects exceed this limit. To accommodate those, we should always make a request for the
                // date range of the graph, and not rely on the annotations in the store.

                const filteredAnnotations = dateRange
                    ? annotations.filter(
                          (annotation: AnnotationType) =>
                              (annotation.scope !== AnnotationScope.Insight ||
                                  annotation.dashboard_item === insightNumericId) &&
                              (annotation.scope !== AnnotationScope.Dashboard ||
                                  annotation.dashboard_item === insightNumericId ||
                                  (dashboardId
                                      ? // on dashboard page, only show annotations if scoped to this dashboard
                                        annotation.dashboard_id === dashboardId
                                      : // on insight page, show annotation if insight is on any dashboard which this annotation is scoped to
                                        savedInsight?.dashboard_tiles?.find(
                                            ({ dashboard_id }) => dashboard_id === annotation.dashboard_id
                                        ))) &&
                              annotation.date_marker &&
                              annotation.date_marker >= dateRange[0] &&
                              annotation.date_marker < dateRange[1]
                      )
                    : []

                // Add special annotation for January 6th and 7th if person property filters or breakdown are present
                // The incident period was Jan 6, 8:01pm UTC - Jan 7, 2:52pm UTC
                if (
                    dateRange &&
                    hasPersonPropertyFiltersOrBreakdown(properties, breakdownFilter) &&
                    featureFlags[FEATURE_FLAGS.PERSON_PROPERTY_INCIDENT_ANNOTATION_JAN_2026]
                ) {
                    const incidentDates = ['2026-01-06', '2026-01-07']
                    const specialAnnotations: DatedAnnotationType[] = incidentDates
                        .map((dateStr, index) => {
                            const dateInTimezone = dayjsLocalToTimezone(dateStr, timezone).startOf('day')

                            // Only include if date is within the date range
                            if (dateInTimezone >= dateRange[0] && dateInTimezone < dateRange[1]) {
                                return {
                                    id: -(index + 1), // -1 for Jan 6, -2 for Jan 7
                                    scope: AnnotationScope.Project,
                                    content:
                                        'Some person properties may have been set incorrectly on events between January 6, 20:01 UTC and January 7, 14:52 UTC. See https://status.posthog.com/ for more information.',
                                    date_marker: dateInTimezone,
                                    created_at: dayjs(),
                                    updated_at: dayjs().toISOString(),
                                    dashboard_item: null,
                                    deleted: false,
                                } as DatedAnnotationType
                            }
                            return null
                        })
                        .filter((annotation): annotation is DatedAnnotationType => annotation !== null)

                    if (specialAnnotations.length > 0) {
                        return [...filteredAnnotations, ...specialAnnotations] as DatedAnnotationType[]
                    }
                }

                return filteredAnnotations as DatedAnnotationType[]
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
    }),
])
