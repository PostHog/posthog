import { BreakPointFunction, kea } from 'kea'
import equal from 'fast-deep-equal'
import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { autoCaptureEventToDescription, average, percentage, sum } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import type { funnelLogicType } from './funnelLogicType'
import {
    AvailableFeature,
    BinCountValue,
    BreakdownKeyType,
    EntityTypes,
    FilterType,
    FlattenedFunnelStep,
    FlattenedFunnelStepByBreakdown,
    FunnelAPIResponse,
    FunnelConversionWindowTimeUnit,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelCorrelationType,
    FunnelStep,
    FunnelStepRangeEntityFilter,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    FunnelsTimeConversionBins,
    FunnelTimeConversionMetrics,
    FunnelVizType,
    InsightLogicProps,
    InsightType,
    PersonType,
    PropertyFilter,
    PropertyOperator,
    StepOrderValue,
    TeamType,
    TrendResult,
} from '~/types'
import { BIN_COUNT_AUTO, FunnelLayout } from 'lib/constants'

import {
    aggregateBreakdownResult,
    getClampedStepRangeFilter,
    getLastFilledStep,
    getMeanAndStandardDeviation,
    getReferenceStep,
    getVisibilityIndex,
    isBreakdownFunnelResults,
    isStepsEmpty,
    isValidBreakdownParameter,
    getBreakdownStepValues,
    getIncompleteConversionWindowStartDate,
    generateBaselineConversionUrl,
} from './funnelUtils'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { teamLogic } from '../teamLogic'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { userLogic } from 'scenes/userLogic'
import { visibilitySensorLogic } from 'lib/components/VisibilitySensor/visibilitySensorLogic'
import { elementsToAction } from 'scenes/events/createActionFromEvent'
import { groupsModel } from '~/models/groupsModel'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/components/lemonToast'

/* Chosen via heuristics by eyeballing some values
 * Assuming a normal distribution, then 90% of values are within 1.5 standard deviations of the mean
 * which gives a ballpark of 1 highlighting every 10 breakdown values
 */
const DEVIATION_SIGNIFICANCE_MULTIPLIER = 1.5

// List of events that should be excluded, if we don't have an explicit list of
// excluded properties. Copied from
// https://github.com/PostHog/posthog/issues/6474#issuecomment-952044722
export const DEFAULT_EXCLUDED_PERSON_PROPERTIES = [
    '$initial_geoip_postal_code',
    '$initial_geoip_latitude',
    '$initial_geoip_longitude',
    '$geoip_latitude',
    '$geoip_longitude',
    '$geoip_postal_code',
    '$geoip_continent_code',
    '$geoip_continent_name',
    '$initial_geoip_continent_code',
    '$initial_geoip_continent_name',
    '$geoip_time_zone',
    '$geoip_country_code',
    '$geoip_subdivision_1_code',
    '$initial_geoip_subdivision_1_code',
    '$geoip_subdivision_2_code',
    '$initial_geoip_subdivision_2_code',
    '$geoip_subdivision_name',
    '$initial_geoip_subdivision_name',
]

export type openPersonsModelProps = {
    step: FunnelStep
    converted: boolean
}

export const funnelLogic = kea<funnelLogicType>({
    path: (key) => ['scenes', 'funnels', 'funnelLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('insight_funnel'),

    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters', 'insight', 'insightLoading', 'isViewedOnDashboard', 'hiddenLegendKeys'],
            teamLogic,
            ['currentTeamId', 'currentTeam'],
            personPropertiesModel,
            ['personProperties'],
            userLogic,
            ['hasAvailableFeature'],
            groupsModel,
            ['aggregationLabel'],
            groupPropertiesModel,
            ['groupProperties'],
        ],
        actions: [insightLogic(props), ['loadResults', 'loadResultsSuccess', 'toggleVisibility', 'setHiddenById']],
        logic: [eventUsageLogic, dashboardsModel, personsModalLogic],
    }),

    actions: () => ({
        clearFunnel: true,
        setFilters: (filters: Partial<FilterType>, refresh: boolean = false, mergeWithExisting: boolean = true) => ({
            filters,
            refresh,
            mergeWithExisting,
        }),
        setEventExclusionFilters: (filters: Partial<FilterType>) => ({ filters }),
        setOneEventExclusionFilter: (eventFilter: FunnelStepRangeEntityFilter, index: number) => ({
            eventFilter,
            index,
        }),
        saveFunnelInsight: (name: string) => ({ name }),
        openPersonsModalForStep: ({ step, converted }: openPersonsModelProps) => ({
            step,
            converted,
        }),
        openPersonsModalForSeries: ({
            step,
            series,
            converted,
        }: {
            step: FunnelStep
            series: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>
            converted: boolean
        }) => ({
            step,
            series,
            converted,
        }),
        openCorrelationPersonsModal: (correlation: FunnelCorrelation, success: boolean) => ({
            correlation,
            success,
        }),
        setStepReference: (stepReference: FunnelStepReference) => ({ stepReference }),
        changeStepRange: (funnel_from_step?: number, funnel_to_step?: number) => ({
            funnel_from_step,
            funnel_to_step,
        }),
        setIsGroupingOutliers: (isGroupingOutliers) => ({ isGroupingOutliers }),
        setBinCount: (binCount: BinCountValue) => ({ binCount }),
        toggleVisibilityByBreakdown: (breakdownValue?: BreakdownKeyType) => ({ breakdownValue }),
        toggleAdvancedMode: true,

        // Correlation related actions
        setCorrelationTypes: (types: FunnelCorrelationType[]) => ({ types }),
        setPropertyCorrelationTypes: (types: FunnelCorrelationType[]) => ({ types }),
        setCorrelationDetailedFeedback: (comment: string) => ({ comment }),
        setCorrelationFeedbackRating: (rating: number) => ({ rating }),
        setCorrelationDetailedFeedbackVisible: (visible: boolean) => ({ visible }),
        sendCorrelationAnalysisFeedback: true,
        hideSkewWarning: true,
        hideCorrelationAnalysisFeedback: true,
        setFunnelCorrelationDetails: (payload: FunnelCorrelation | null) => ({ payload }),

        setPropertyNames: (propertyNames: string[]) => ({ propertyNames }),
        excludePropertyFromProject: (propertyName: string) => ({ propertyName }),
        excludeEventFromProject: (eventName: string) => ({ eventName }),
        excludeEventPropertyFromProject: (eventName: string, propertyName: string) => ({ eventName, propertyName }),

        addNestedTableExpandedKey: (expandKey: string) => ({ expandKey }),
        removeNestedTableExpandedKey: (expandKey: string) => ({ expandKey }),

        showTooltip: (
            origin: [number, number, number],
            stepIndex: number,
            series: FunnelStepWithConversionMetrics
        ) => ({
            origin,
            stepIndex,
            series,
        }),
        hideTooltip: true,
    }),
    defaults: {
        // This is a hack to get `FunnelCorrelationResultsType` imported in `funnelLogicType.ts`
        __ignore: null as FunnelCorrelationResultsType | null,
    },
    loaders: ({ values }) => ({
        people: [
            [] as any[],
            {
                loadPeople: async (steps) => {
                    return (await api.get('api/person/?uuid=' + steps[0].people.join(','))).results
                },
            },
        ],
        correlations: [
            { events: [] } as Record<'events', FunnelCorrelation[]>,
            {
                loadCorrelations: async (_, breakpoint) => {
                    await breakpoint(100)

                    try {
                        const results: Omit<FunnelCorrelation, 'result_type'>[] = (
                            await api.create(`api/projects/${values.currentTeamId}/insights/funnel/correlation`, {
                                ...values.apiParams,
                                funnel_correlation_type: 'events',
                                funnel_correlation_exclude_event_names: values.excludedEventNames,
                            })
                        ).result?.events

                        return {
                            events: results.map((result) => ({
                                ...result,
                                result_type: FunnelCorrelationResultsType.Events,
                            })),
                        }
                    } catch (error) {
                        lemonToast.error('Failed to load correlation results', { toastId: 'funnel-correlation-error' })
                        return { events: [] }
                    }
                },
            },
        ],
        propertyCorrelations: [
            { events: [] } as Record<'events', FunnelCorrelation[]>,
            {
                loadPropertyCorrelations: async (_, breakpoint) => {
                    const targetProperties =
                        values.propertyNames.length >= values.allProperties.length ? ['$all'] : values.propertyNames

                    if (targetProperties.length === 0) {
                        return { events: [] }
                    }

                    await breakpoint(100)

                    try {
                        const results: Omit<FunnelCorrelation, 'result_type'>[] = (
                            await api.create(`api/projects/${values.currentTeamId}/insights/funnel/correlation`, {
                                ...values.apiParams,
                                funnel_correlation_type: 'properties',
                                funnel_correlation_names: targetProperties,
                                funnel_correlation_exclude_names: values.excludedPropertyNames,
                            })
                        ).result?.events

                        return {
                            events: results.map((result) => ({
                                ...result,
                                result_type: FunnelCorrelationResultsType.Properties,
                            })),
                        }
                    } catch (error) {
                        lemonToast.error('Failed to load correlation results', { toastId: 'funnel-correlation-error' })
                        return { events: [] }
                    }
                },
            },
        ],
        eventWithPropertyCorrelations: [
            {} as Record<string, FunnelCorrelation[]>,
            {
                loadEventWithPropertyCorrelations: async (eventName: string) => {
                    const results: Omit<FunnelCorrelation, 'result_type'>[] = (
                        await api.create(`api/projects/${values.currentTeamId}/insights/funnel/correlation`, {
                            ...values.apiParams,
                            funnel_correlation_type: 'event_with_properties',
                            funnel_correlation_event_names: [eventName],
                            funnel_correlation_event_exclude_property_names: values.excludedEventPropertyNames,
                        })
                    ).result?.events

                    eventUsageLogic.actions.reportCorrelationInteraction(
                        FunnelCorrelationResultsType.EventWithProperties,
                        'load event with properties',
                        { name: eventName }
                    )

                    return {
                        [eventName]: results.map((result) => ({
                            ...result,
                            result_type: FunnelCorrelationResultsType.EventWithProperties,
                        })),
                    }
                },
            },
        ],
    }),

    reducers: ({ props }) => ({
        people: {
            clearFunnel: () => [],
        },
        stepReference: [
            FunnelStepReference.total as FunnelStepReference,
            {
                setStepReference: (_, { stepReference }) => stepReference,
            },
        ],
        isGroupingOutliers: [
            true,
            {
                setIsGroupingOutliers: (_, { isGroupingOutliers }) => isGroupingOutliers,
            },
        ],
        error: [
            null as any,
            {
                [insightLogic(props).actionTypes.startQuery]: () => null,
                [insightLogic(props).actionTypes.endQuery]: (_: any, { exception }: any) => exception ?? null,
                [insightLogic(props).actionTypes.abortQuery]: (_: any, { exception }: any) => exception ?? null,
            },
        ],
        correlationTypes: [
            [FunnelCorrelationType.Success, FunnelCorrelationType.Failure] as FunnelCorrelationType[],
            {
                setCorrelationTypes: (_, { types }) => types,
            },
        ],
        propertyCorrelationTypes: [
            [FunnelCorrelationType.Success, FunnelCorrelationType.Failure] as FunnelCorrelationType[],
            {
                setPropertyCorrelationTypes: (_, { types }) => types,
            },
        ],
        skewWarningHidden: [
            false,
            {
                hideSkewWarning: () => true,
            },
        ],
        correlationFeedbackHidden: [
            false,
            {
                sendCorrelationAnalysisFeedback: () => true,
                hideCorrelationAnalysisFeedback: () => true,
            },
        ],
        correlationDetailedFeedbackVisible: [
            false,
            {
                setCorrelationDetailedFeedbackVisible: (_, { visible }) => visible,
            },
        ],
        correlationFeedbackRating: [
            0,
            {
                setCorrelationFeedbackRating: (_, { rating }) => rating,
            },
        ],
        correlationDetailedFeedback: [
            '',
            {
                setCorrelationDetailedFeedback: (_, { comment }) => comment,
            },
        ],
        eventWithPropertyCorrelations: {
            loadEventWithPropertyCorrelationsSuccess: (state, { eventWithPropertyCorrelations }) => {
                return {
                    ...state,
                    ...eventWithPropertyCorrelations,
                }
            },
            loadCorrelationsSuccess: () => {
                return {}
            },
        },
        propertyNames: [
            [] as string[],
            {
                setPropertyNames: (_, { propertyNames }) => propertyNames,
                excludePropertyFromProject: (selectedProperties, { propertyName }) => {
                    return selectedProperties.filter((p) => p !== propertyName)
                },
            },
        ],
        nestedTableExpandedKeys: [
            [] as string[],
            {
                removeNestedTableExpandedKey: (state, { expandKey }) => {
                    return state.filter((key) => key !== expandKey)
                },
                addNestedTableExpandedKey: (state, { expandKey }) => {
                    return [...state, expandKey]
                },
                loadCorrelationsSuccess: () => {
                    return []
                },
            },
        ],
        shouldReportCorrelationViewed: [
            true as boolean,
            {
                loadResultsSuccess: () => true,
                [eventUsageLogic.actionTypes.reportCorrelationViewed]: (current, { propertiesTable }) => {
                    if (!propertiesTable) {
                        return false // don't report correlation viewed again, since it was for events earlier
                    }
                    return current
                },
            },
        ],
        shouldReportPropertyCorrelationViewed: [
            true as boolean,
            {
                loadResultsSuccess: () => true,
                [eventUsageLogic.actionTypes.reportCorrelationViewed]: (current, { propertiesTable }) => {
                    if (propertiesTable) {
                        return false
                    }
                    return current
                },
            },
        ],
        funnelCorrelationDetails: [
            null as null | FunnelCorrelation,
            {
                setFunnelCorrelationDetails: (_, { payload }) => payload,
            },
        ],
        isTooltipShown: [
            false,
            {
                showTooltip: () => true,
                hideTooltip: () => false,
            },
        ],
        currentTooltip: [
            null as [number, FunnelStepWithConversionMetrics] | null,
            {
                showTooltip: (_, { stepIndex, series }) => [stepIndex, series],
            },
        ],
        tooltipOrigin: [
            null as [number, number, number] | null, // x, y, width
            {
                showTooltip: (_, { origin }) => origin,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        loadedFilters: [(s) => [s.insight], ({ filters }) => (filters?.insight === InsightType.FUNNELS ? filters : {})],
        results: [
            (s) => [s.insight],
            ({ filters, result }): FunnelAPIResponse => {
                if (filters?.insight === InsightType.FUNNELS) {
                    if (Array.isArray(result) && Array.isArray(result[0]) && result[0][0].breakdowns) {
                        // in order to stop the UI having to check breakdowns and breakdown
                        // this collapses breakdowns onto the breakdown property
                        return result.map((series) =>
                            series.map((r: { [x: string]: any; breakdowns: any; breakdown_value: any }) => {
                                const { breakdowns, breakdown_value, ...singlePropertyClone } = r
                                singlePropertyClone.breakdown = breakdowns
                                singlePropertyClone.breakdown_value = breakdown_value
                                return singlePropertyClone
                            })
                        )
                    }
                    return result
                } else {
                    return []
                }
            },
        ],
        conversionWindow: [
            (s) => [s.filters],
            ({ funnel_window_interval, funnel_window_interval_unit }) => ({
                funnel_window_interval: funnel_window_interval || 14,
                funnel_window_interval_unit: funnel_window_interval_unit || FunnelConversionWindowTimeUnit.Day,
            }),
        ],
        timeConversionResults: [
            (s) => [s.results, s.filters],
            (results, filters): FunnelsTimeConversionBins | null => {
                return filters.funnel_viz_type === FunnelVizType.TimeToConvert
                    ? (results as FunnelsTimeConversionBins)
                    : null
            },
        ],
        peopleSorted: [
            () => [selectors.stepsWithCount, selectors.people],
            (steps, people) => {
                if (!people) {
                    return null
                }
                const score = (person: PersonType): number => {
                    return steps.reduce(
                        (val, step) => (person.uuid && (step.people?.indexOf(person.uuid) ?? -1) > -1 ? val + 1 : val),
                        0
                    )
                }
                return [...people].sort((a, b) => score(b) - score(a))
            },
        ],
        isStepsEmpty: [() => [selectors.filters], (filters: FilterType) => isStepsEmpty(filters)],
        propertiesForUrl: [() => [selectors.filters], (filters: FilterType) => cleanFilters(filters)],
        isValidFunnel: [
            () => [selectors.filters, selectors.stepsWithCount, selectors.histogramGraphData],
            (filters, stepsWithCount, histogramGraphData) => {
                if (filters.funnel_viz_type === FunnelVizType.Steps || !filters.funnel_viz_type) {
                    return !!(stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1)
                }
                if (filters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return (histogramGraphData?.length ?? 0) > 0
                }
                if (filters.funnel_viz_type === FunnelVizType.Trends) {
                    return (stepsWithCount?.length ?? 0) > 0 && stepsWithCount?.[0]?.labels
                }
                return false
            },
        ],
        filtersDirty: [
            () => [selectors.filters, selectors.loadedFilters],
            (filters, lastFilters): boolean => !equal(cleanFilters(filters), cleanFilters(lastFilters)),
        ],
        barGraphLayout: [() => [selectors.filters], ({ layout }): FunnelLayout => layout || FunnelLayout.vertical],
        histogramGraphData: [
            () => [selectors.timeConversionResults],
            (timeConversionResults: FunnelsTimeConversionBins) => {
                if ((timeConversionResults?.bins?.length ?? 0) < 2) {
                    return []
                }
                const binSize = timeConversionResults.bins[1][0] - timeConversionResults.bins[0][0]
                const totalCount = sum(timeConversionResults.bins.map(([, count]) => count))
                return timeConversionResults.bins.map(([id, count]: [id: number, count: number]) => {
                    const value = Math.max(0, id)
                    const percent = count / totalCount
                    return {
                        id: value,
                        bin0: value,
                        bin1: value + binSize,
                        count,
                        label: percent === 0 ? '' : percentage(percent, 1, true),
                    }
                })
            },
        ],
        areFiltersValid: [
            () => [selectors.numberOfSeries],
            (numberOfSeries) => {
                return numberOfSeries > 1
            },
        ],
        numberOfSeries: [
            () => [selectors.filters],
            (filters): number => (filters.events?.length || 0) + (filters.actions?.length || 0),
        ],
        conversionMetrics: [
            () => [selectors.stepsWithCount, selectors.loadedFilters, selectors.timeConversionResults],
            (stepsWithCount, loadedFilters, timeConversionResults): FunnelTimeConversionMetrics => {
                // stepsWithCount should be empty in time conversion view. Return metrics precalculated on backend
                if (loadedFilters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return {
                        averageTime: timeConversionResults?.average_conversion_time ?? 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                // Handle metrics for trends
                if (loadedFilters.funnel_viz_type === FunnelVizType.Trends) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: average((stepsWithCount?.[0] as unknown as TrendResult)?.data ?? []) / 100,
                    }
                }

                // Handle metrics for steps
                // no concept of funnel_from_step and funnel_to_step here
                if (stepsWithCount.length <= 1) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                const toStep = getLastFilledStep(stepsWithCount)
                const fromStep = getReferenceStep(stepsWithCount, FunnelStepReference.total)

                return {
                    averageTime: stepsWithCount.reduce(
                        (conversion_time, step) => conversion_time + (step.average_conversion_time || 0),
                        0
                    ),
                    stepRate: toStep.count / fromStep.count,
                    totalRate: stepsWithCount[stepsWithCount.length - 1].count / stepsWithCount[0].count,
                }
            },
        ],
        isSkewed: [
            (s) => [s.conversionMetrics, s.skewWarningHidden],
            (conversionMetrics, skewWarningHidden): boolean => {
                return !skewWarningHidden && (conversionMetrics.totalRate < 0.1 || conversionMetrics.totalRate > 0.9)
            },
        ],
        apiParams: [
            (s) => [s.filters],
            (filters) => {
                /* TODO: Related to #4329. We're mixing `from_dashboard` as both which causes hard to manage code:
                    a) a boolean-based hash param to determine if the insight is saved in a dashboard (when viewing insights page)
                    b) dashboard ID passed as a filter in certain kind of insights when viewing in the dashboard page
                */
                const { from_dashboard } = filters
                const cleanedParams = cleanFilters(filters)
                return {
                    ...(from_dashboard ? { from_dashboard } : {}),
                    ...cleanedParams,
                }
            },
        ],
        filterSteps: [
            () => [selectors.apiParams],
            (apiParams) =>
                [...(apiParams.events ?? []), ...(apiParams.actions ?? []), ...(apiParams.new_entity ?? [])].sort(
                    (a, b) => a.order - b.order
                ),
        ],
        eventCount: [() => [selectors.apiParams], (apiParams) => apiParams.events?.length || 0],
        actionCount: [() => [selectors.apiParams], (apiParams) => apiParams.actions?.length || 0],
        interval: [() => [selectors.apiParams], (apiParams) => apiParams.interval || ''],
        steps: [
            (s) => [s.filters, s.results, s.apiParams],
            (filters: Partial<FilterType>, results: FunnelAPIResponse, apiParams): FunnelStepWithNestedBreakdown[] => {
                const stepResults =
                    filters.funnel_viz_type !== FunnelVizType.TimeToConvert
                        ? (results as FunnelStep[] | FunnelStep[][])
                        : []

                if (!Array.isArray(stepResults)) {
                    return []
                }

                let stepsWithNestedBreakdown: FunnelStepWithNestedBreakdown[] = []
                if (
                    isBreakdownFunnelResults(results) &&
                    isValidBreakdownParameter(apiParams.breakdown, apiParams.breakdowns)
                ) {
                    const breakdownProperty = apiParams.breakdowns
                        ? apiParams.breakdowns.map((b) => b.property).join('::')
                        : apiParams.breakdown ?? undefined
                    stepsWithNestedBreakdown = aggregateBreakdownResult(results, breakdownProperty).sort(
                        (a, b) => a.order - b.order
                    )
                }

                return !!filters.breakdowns || !!filters.breakdown
                    ? stepsWithNestedBreakdown
                    : ([...stepResults] as FunnelStep[]).sort((a, b) => a.order - b.order)
            },
        ],
        stepsWithCount: [
            () => [selectors.steps],
            (steps) => steps.filter((step) => typeof step.count === 'number' && step.count > 0),
        ],
        stepsWithConversionMetrics: [
            () => [selectors.steps, selectors.stepReference],
            (steps, stepReference): FunnelStepWithConversionMetrics[] => {
                const stepsWithConversionMetrics = steps.map((step, i) => {
                    const previousCount = i > 0 ? steps[i - 1].count : step.count // previous is faked for the first step
                    const droppedOffFromPrevious = Math.max(previousCount - step.count, 0)

                    const nestedBreakdown = step.nested_breakdown?.map((breakdown, breakdownIndex) => {
                        const firstBreakdownCount = steps[0]?.nested_breakdown?.[breakdownIndex].count || 0
                        // firstBreakdownCount serves as previousBreakdownCount for the first step so that
                        // "Relative to previous step" is shown correctly – later series use the actual previous steps
                        const previousBreakdownCount =
                            i === 0 ? firstBreakdownCount : steps[i - 1].nested_breakdown?.[breakdownIndex].count || 0
                        const nestedDroppedOffFromPrevious = Math.max(previousBreakdownCount - breakdown.count, 0)
                        const conversionRates = {
                            fromPrevious: previousBreakdownCount === 0 ? 0 : breakdown.count / previousBreakdownCount,
                            total: breakdown.count / firstBreakdownCount,
                        }
                        return {
                            ...breakdown,
                            droppedOffFromPrevious: nestedDroppedOffFromPrevious,
                            conversionRates: {
                                ...conversionRates,
                                fromBasisStep:
                                    stepReference === FunnelStepReference.total
                                        ? conversionRates.total
                                        : conversionRates.fromPrevious,
                            },
                        }
                    })
                    const conversionRates = {
                        fromPrevious: previousCount === 0 ? 0 : step.count / previousCount,
                        total: step.count / steps[0].count,
                    }
                    return {
                        ...step,
                        droppedOffFromPrevious,
                        nested_breakdown: nestedBreakdown,
                        conversionRates: {
                            ...conversionRates,
                            fromBasisStep:
                                i > 0
                                    ? stepReference === FunnelStepReference.total
                                        ? conversionRates.total
                                        : conversionRates.fromPrevious
                                    : conversionRates.total,
                        },
                    }
                })

                if (!stepsWithConversionMetrics.length || !stepsWithConversionMetrics[0].nested_breakdown) {
                    return stepsWithConversionMetrics
                }

                return stepsWithConversionMetrics.map((step) => {
                    // Per step breakdown significance
                    const [meanFromPrevious, stdDevFromPrevious] = getMeanAndStandardDeviation(
                        step.nested_breakdown?.map((item) => item.conversionRates.fromPrevious)
                    )
                    const [meanFromBasis, stdDevFromBasis] = getMeanAndStandardDeviation(
                        step.nested_breakdown?.map((item) => item.conversionRates.fromBasisStep)
                    )
                    const [meanTotal, stdDevTotal] = getMeanAndStandardDeviation(
                        step.nested_breakdown?.map((item) => item.conversionRates.total)
                    )

                    const isOutlier = (value: number, mean: number, stdDev: number): boolean => {
                        return (
                            value > mean + stdDev * DEVIATION_SIGNIFICANCE_MULTIPLIER ||
                            value < mean - stdDev * DEVIATION_SIGNIFICANCE_MULTIPLIER
                        )
                    }

                    const nestedBreakdown = step.nested_breakdown?.map((item) => {
                        return {
                            ...item,
                            significant: {
                                fromPrevious: isOutlier(
                                    item.conversionRates.fromPrevious,
                                    meanFromPrevious,
                                    stdDevFromPrevious
                                ),
                                fromBasisStep: isOutlier(
                                    item.conversionRates.fromBasisStep,
                                    meanFromBasis,
                                    stdDevFromBasis
                                ),
                                total: isOutlier(item.conversionRates.total, meanTotal, stdDevTotal),
                            },
                        }
                    })

                    return {
                        ...step,
                        nested_breakdown: nestedBreakdown,
                    }
                })
            },
        ],
        visibleStepsWithConversionMetrics: [
            () => [
                selectors.stepsWithConversionMetrics,
                selectors.hiddenLegendKeys,
                selectors.flattenedStepsByBreakdown,
            ],
            (steps, hiddenLegendKeys, flattenedStepsByBreakdown): FunnelStepWithConversionMetrics[] => {
                const baseLineSteps = flattenedStepsByBreakdown.find((b) => b.isBaseline)
                return steps.map((step, stepIndex) => ({
                    ...step,
                    nested_breakdown: (!!baseLineSteps?.steps
                        ? [baseLineSteps.steps[stepIndex], ...(step?.nested_breakdown ?? [])]
                        : step?.nested_breakdown
                    )
                        ?.map((b, breakdownIndex) => ({
                            ...b,
                            order: breakdownIndex,
                        }))
                        ?.filter((b) => {
                            return !hiddenLegendKeys[getVisibilityIndex(step, b.breakdown_value)]
                        }),
                }))
            },
        ],
        flattenedSteps: [
            () => [selectors.stepsWithConversionMetrics],
            (steps): FlattenedFunnelStep[] => {
                const flattenedSteps: FlattenedFunnelStep[] = []
                steps.forEach((step) => {
                    const isBreakdownParent = !!step.nested_breakdown?.length
                    flattenedSteps.push({
                        ...step,
                        rowKey: step.order,
                        nestedRowKeys: step.nested_breakdown
                            ? step.nested_breakdown.map((breakdownStep) =>
                                  getVisibilityIndex(step, breakdownStep.breakdown_value)
                              )
                            : [],
                        isBreakdownParent,
                        breakdown_value: isBreakdownParent ? ['Baseline'] : step.breakdown_value,
                        breakdown: isBreakdownParent ? ['baseline'] : step.breakdown,
                    })
                    if (step.nested_breakdown?.length) {
                        step.nested_breakdown.forEach((breakdownStep, i) => {
                            flattenedSteps.push({
                                ...breakdownStep,
                                order: step.order,
                                breakdownIndex: i,
                                rowKey: getVisibilityIndex(step, breakdownStep.breakdown_value),
                                isBreakdownParent: false,
                            })
                        })
                    }
                })
                return flattenedSteps
            },
        ],
        flattenedStepsByBreakdown: [
            () => [selectors.stepsWithConversionMetrics, selectors.barGraphLayout],
            (steps, layout): FlattenedFunnelStepByBreakdown[] => {
                // Initialize with two rows for rendering graph and header
                const flattenedStepsByBreakdown: FlattenedFunnelStepByBreakdown[] = [
                    { rowKey: 'steps-meta' },
                    { rowKey: 'graph' },
                    { rowKey: 'table-header' },
                ]
                if (steps.length > 0) {
                    const baseStep = steps[0]
                    const lastStep = steps[steps.length - 1]
                    const hasBaseline =
                        !baseStep.breakdown ||
                        (layout === FunnelLayout.vertical && (baseStep.nested_breakdown?.length ?? 0) > 1)
                    // Baseline - total step to step metrics, only add if more than 1 breakdown or not breakdown
                    if (hasBaseline) {
                        flattenedStepsByBreakdown.push({
                            ...getBreakdownStepValues(baseStep, 0, true),
                            isBaseline: true,
                            breakdownIndex: 0,
                            steps: steps.map((s) => ({
                                ...s,
                                nested_breakdown: undefined,
                                breakdown_value: 'Baseline',
                                converted_people_url: generateBaselineConversionUrl(s.converted_people_url),
                                dropped_people_url: generateBaselineConversionUrl(s.dropped_people_url),
                            })),
                            conversionRates: {
                                total: (lastStep?.count ?? 0) / (baseStep?.count ?? 1),
                            },
                        })
                    }
                    // Per Breakdown
                    if (baseStep.nested_breakdown?.length) {
                        baseStep.nested_breakdown.forEach((breakdownStep, i) => {
                            const stepsInBreakdown = steps
                                .filter((s) => !!s?.nested_breakdown?.[i])
                                .map((s) => s.nested_breakdown?.[i] as FunnelStepWithConversionMetrics)
                            const offset = hasBaseline ? 1 : 0
                            flattenedStepsByBreakdown.push({
                                ...getBreakdownStepValues(breakdownStep, i + offset),
                                isBaseline: false,
                                breakdownIndex: i + offset,
                                steps: stepsInBreakdown,
                                conversionRates: {
                                    total:
                                        (stepsInBreakdown[stepsInBreakdown.length - 1]?.count ?? 0) /
                                        (stepsInBreakdown[0]?.count ?? 1),
                                },
                                significant: stepsInBreakdown.some(
                                    (step) => step.significant?.total || step.significant?.fromPrevious
                                ),
                            })
                        })
                    }
                }
                return flattenedStepsByBreakdown
            },
        ],
        flattenedBreakdowns: [
            () => [selectors.flattenedStepsByBreakdown],
            (breakdowns): FlattenedFunnelStepByBreakdown[] => {
                return breakdowns.filter((b) => b.breakdown)
            },
        ],
        numericBinCount: [
            () => [selectors.filters, selectors.timeConversionResults],
            (filters, timeConversionResults): number => {
                if (filters.bin_count === BIN_COUNT_AUTO) {
                    return timeConversionResults?.bins?.length ?? 0
                }
                return filters.bin_count ?? 0
            },
        ],
        exclusionDefaultStepRange: [
            () => [selectors.numberOfSeries, selectors.areFiltersValid],
            (numberOfSeries, areFiltersValid): Omit<FunnelStepRangeEntityFilter, 'id' | 'name'> => ({
                funnel_from_step: 0,
                funnel_to_step: areFiltersValid ? numberOfSeries - 1 : 1,
            }),
        ],
        exclusionFilters: [
            () => [selectors.filters],
            (filters: FilterType): FilterType => ({
                events: filters.exclusions,
            }),
        ],
        areExclusionFiltersValid: [
            () => [selectors.error],
            (e: any): boolean => {
                return !(e?.status === 400 && e?.type === 'validation_error')
            },
        ],
        correlationValues: [
            () => [selectors.correlations, selectors.correlationTypes, selectors.excludedEventNames],
            (correlations, correlationTypes, excludedEventNames): FunnelCorrelation[] => {
                return correlations.events
                    ?.filter(
                        (correlation) =>
                            correlationTypes.includes(correlation.correlation_type) &&
                            !excludedEventNames.includes(correlation.event.event)
                    )
                    .map((value) => {
                        return {
                            ...value,
                            odds_ratio:
                                value.correlation_type === FunnelCorrelationType.Success
                                    ? value.odds_ratio
                                    : 1 / value.odds_ratio,
                        }
                    })
                    .sort((first, second) => {
                        return second.odds_ratio - first.odds_ratio
                    })
            },
        ],
        propertyCorrelationValues: [
            () => [selectors.propertyCorrelations, selectors.propertyCorrelationTypes, selectors.excludedPropertyNames],
            (propertyCorrelations, propertyCorrelationTypes, excludedPropertyNames): FunnelCorrelation[] => {
                return propertyCorrelations.events
                    .filter(
                        (correlation) =>
                            propertyCorrelationTypes.includes(correlation.correlation_type) &&
                            !excludedPropertyNames.includes(correlation.event.event.split('::')[0])
                    )
                    .map((value) => {
                        return {
                            ...value,
                            odds_ratio:
                                value.correlation_type === FunnelCorrelationType.Success
                                    ? value.odds_ratio
                                    : 1 / value.odds_ratio,
                        }
                    })
                    .sort((first, second) => {
                        return second.odds_ratio - first.odds_ratio
                    })
            },
        ],
        eventWithPropertyCorrelationsValues: [
            () => [
                selectors.eventWithPropertyCorrelations,
                selectors.correlationTypes,
                selectors.excludedEventPropertyNames,
            ],
            (
                eventWithPropertyCorrelations,
                correlationTypes,
                excludedEventPropertyNames
            ): Record<string, FunnelCorrelation[]> => {
                const eventWithPropertyCorrelationsValues: Record<string, FunnelCorrelation[]> = {}
                for (const key in eventWithPropertyCorrelations) {
                    if (eventWithPropertyCorrelations.hasOwnProperty(key)) {
                        eventWithPropertyCorrelationsValues[key] = eventWithPropertyCorrelations[key]
                            ?.filter(
                                (correlation) =>
                                    correlationTypes.includes(correlation.correlation_type) &&
                                    !excludedEventPropertyNames.includes(correlation.event.event.split('::')[1])
                            )
                            .map((value) => {
                                return {
                                    ...value,
                                    odds_ratio:
                                        value.correlation_type === FunnelCorrelationType.Success
                                            ? value.odds_ratio
                                            : 1 / value.odds_ratio,
                                }
                            })
                            .sort((first, second) => {
                                return second.odds_ratio - first.odds_ratio
                            })
                    }
                }
                return eventWithPropertyCorrelationsValues
            },
        ],
        eventHasPropertyCorrelations: [
            () => [selectors.eventWithPropertyCorrelationsValues],
            (eventWithPropertyCorrelationsValues): ((eventName: string) => boolean) => {
                return (eventName) => {
                    return !!eventWithPropertyCorrelationsValues[eventName]
                }
            },
        ],
        parseDisplayNameForCorrelation: [
            () => [],
            (): ((record: FunnelCorrelation) => {
                first_value: string
                second_value?: string
            }) => {
                return (record) => {
                    let first_value = undefined
                    let second_value = undefined
                    const values = record.event.event.split('::')

                    if (record.result_type === FunnelCorrelationResultsType.Events) {
                        first_value = record.event.event
                        return { first_value, second_value }
                    } else if (record.result_type === FunnelCorrelationResultsType.Properties) {
                        first_value = values[0]
                        second_value = values[1]
                        return { first_value, second_value }
                    } else if (values[0] === '$autocapture' && values[1] === 'elements_chain') {
                        // special case for autocapture elements_chain
                        first_value = autoCaptureEventToDescription({
                            ...record.event,
                            event: '$autocapture',
                        }) as string
                        return { first_value, second_value }
                    } else {
                        // FunnelCorrelationResultsType.EventWithProperties
                        // Events here come in the form of event::property::value
                        return { first_value: values[1], second_value: values[2] }
                    }
                }
            },
        ],
        correlationPropKey: [
            () => [(_, props) => props],
            (props): string => `correlation-${keyForInsightLogicProps('insight_funnel')(props)}`,
        ],

        isPropertyExcludedFromProject: [
            () => [selectors.excludedPropertyNames],
            (excludedPropertyNames) => (propertyName: string) =>
                excludedPropertyNames.find((name) => name === propertyName) !== undefined,
        ],
        isEventExcluded: [
            () => [selectors.excludedEventNames],
            (excludedEventNames) => (eventName: string) =>
                excludedEventNames.find((name) => name === eventName) !== undefined,
        ],

        isEventPropertyExcluded: [
            () => [selectors.excludedEventPropertyNames],
            (excludedEventPropertyNames) => (propertyName: string) =>
                excludedEventPropertyNames.find((name) => name === propertyName) !== undefined,
        ],
        excludedPropertyNames: [
            () => [selectors.currentTeam],
            (currentTeam) =>
                currentTeam?.correlation_config?.excluded_person_property_names || DEFAULT_EXCLUDED_PERSON_PROPERTIES,
        ],
        excludedEventNames: [
            () => [selectors.currentTeam],
            (currentTeam) => currentTeam?.correlation_config?.excluded_event_names || [],
        ],
        excludedEventPropertyNames: [
            () => [selectors.currentTeam],
            (currentTeam) => currentTeam?.correlation_config?.excluded_event_property_names || [],
        ],
        inversePropertyNames: [
            (s) => [s.filters, s.personProperties, s.groupProperties],
            (filters, personProperties, groupProperties) => (excludedPersonProperties: string[]) => {
                const targetProperties =
                    filters.aggregation_group_type_index !== undefined
                        ? groupProperties(filters.aggregation_group_type_index)
                        : personProperties
                return targetProperties
                    .map((property) => property.name)
                    .filter((property) => !excludedPersonProperties.includes(property))
            },
        ],
        correlationAnalysisAvailable: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.CORRELATION_ANALYSIS),
        ],
        allProperties: [
            (s) => [s.inversePropertyNames, s.excludedPropertyNames],
            (inversePropertyNames, excludedPropertyNames): string[] => {
                return inversePropertyNames(excludedPropertyNames || [])
            },
        ],
        aggregationTargetLabel: [
            (s) => [s.filters, s.aggregationLabel],
            (
                filters,
                aggregationLabel
            ): {
                singular: string
                plural: string
            } => aggregationLabel(filters.aggregation_group_type_index),
        ],
        correlationMatrixAndScore: [
            (s) => [s.funnelCorrelationDetails, s.steps],
            (
                funnelCorrelationDetails,
                steps
            ): {
                truePositive: number
                falsePositive: number
                trueNegative: number
                falseNegative: number
                correlationScore: number
                correlationScoreStrength: 'weak' | 'moderate' | 'strong' | null
            } => {
                if (!funnelCorrelationDetails) {
                    return {
                        truePositive: 0,
                        falsePositive: 0,
                        trueNegative: 0,
                        falseNegative: 0,
                        correlationScore: 0,
                        correlationScoreStrength: null,
                    }
                }

                const successTotal = steps[steps.length - 1].count
                const failureTotal = steps[0].count - successTotal
                const success = funnelCorrelationDetails.success_count
                const failure = funnelCorrelationDetails.failure_count

                const truePositive = success // has property, converted
                const falseNegative = failure // has property, but dropped off
                const trueNegative = failureTotal - failure // doesn't have property, dropped off
                const falsePositive = successTotal - success // doesn't have property, converted

                // Phi coefficient: https://en.wikipedia.org/wiki/Phi_coefficient
                const correlationScore =
                    (truePositive * trueNegative - falsePositive * falseNegative) /
                    Math.sqrt(
                        (truePositive + falsePositive) *
                            (truePositive + falseNegative) *
                            (trueNegative + falsePositive) *
                            (trueNegative + falseNegative)
                    )

                const correlationScoreStrength =
                    Math.abs(correlationScore) > 0.5 ? 'strong' : Math.abs(correlationScore) > 0.3 ? 'moderate' : 'weak'

                return {
                    correlationScore,
                    truePositive,
                    falsePositive,
                    trueNegative,
                    falseNegative,
                    correlationScoreStrength,
                }
            },
        ],
        advancedOptionsUsedCount: [
            (s) => [s.filters, s.stepReference],
            (filters: FilterType, stepReference: FunnelStepReference): number => {
                let count = 0
                if (filters.funnel_order_type && filters.funnel_order_type !== StepOrderValue.ORDERED) {
                    count = count + 1
                }
                if (stepReference !== FunnelStepReference.total) {
                    count = count + 1
                }
                if (filters.exclusions?.length) {
                    count = count + 1
                }
                return count
            },
        ],
        isModalActive: [(s) => [s.isViewedOnDashboard], (isViewedOnDashboard) => !isViewedOnDashboard],
        incompletenessOffsetFromEnd: [
            (s) => [s.steps, s.conversionWindow],
            (steps, conversionWindow) => {
                // Returns negative number of points to paint over starting from end of array
                if (steps?.[0]?.days === undefined) {
                    return 0
                }
                const startDate = getIncompleteConversionWindowStartDate(conversionWindow)
                const startIndex = steps[0].days.findIndex((day) => dayjs(day) >= startDate)

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - steps[0].days.length
                } else {
                    return 0
                }
            },
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        loadResultsSuccess: async ({ insight }) => {
            if (insight.filters?.insight !== InsightType.FUNNELS) {
                return
            }
            // hide all but the first five breakdowns for each step
            values.steps?.forEach((step) => {
                values.flattenedStepsByBreakdown
                    ?.filter((s) => !!s.breakdown)
                    ?.slice(5)
                    .forEach((b) => {
                        actions.setHiddenById({ [getVisibilityIndex(step, b.breakdown_value)]: true })
                    })
            })
        },
        toggleVisibilityByBreakdown: ({ breakdownValue }) => {
            values.visibleStepsWithConversionMetrics?.forEach((step) => {
                const key = getVisibilityIndex(step, breakdownValue)
                const currentIsHidden = !!values.hiddenLegendKeys?.[key]
                actions.setHiddenById({ [key]: currentIsHidden ? undefined : true })
            })
        },
        setFilters: ({ filters, mergeWithExisting }) => {
            const cleanedParams = cleanFilters(
                mergeWithExisting
                    ? {
                          ...values.filters,
                          ...filters,
                      }
                    : filters,
                values.filters
            )
            insightLogic(props).actions.setFilters(cleanedParams)
        },
        setEventExclusionFilters: ({ filters }) => {
            const exclusions = (filters.events as FunnelStepRangeEntityFilter[]).map((exclusion) => {
                exclusion.funnel_from_step =
                    exclusion.funnel_from_step || values.exclusionDefaultStepRange.funnel_from_step
                exclusion.funnel_to_step = exclusion.funnel_to_step || values.exclusionDefaultStepRange.funnel_to_step
                return exclusion
            })
            actions.setFilters({
                ...values.filters,
                exclusions,
            })
        },
        setOneEventExclusionFilter: ({ eventFilter, index }) => {
            actions.setFilters({
                ...values.filters,
                exclusions: values.filters.exclusions
                    ? values.filters.exclusions.map((e, e_i) =>
                          e_i === index
                              ? getClampedStepRangeFilter({ stepRange: eventFilter, filters: values.filters })
                              : e
                      )
                    : [],
            })
        },
        clearFunnel: ({}) => {
            actions.setFilters({ new_entity: values.filters.new_entity }, false, true)
        },
        openPersonsModalForStep: ({ step, converted }) => {
            // DEPRECATED
            if (!values.isModalActive) {
                return
            }

            const funnelStep = converted ? step.order : -step.order - 1
            const breakdownValues = getBreakdownStepValues(step, funnelStep)

            personsModalLogic.actions.loadPeopleFromUrl({
                url: converted ? step.converted_people_url : step.dropped_people_url,
                // NOTE: although we have the url that contains all of the info needed
                // to return people, we currently still need to pass something in for the
                // purpose of the modal displaying the label.
                funnelStep: converted ? step.order : -step.order,
                breakdown_value: breakdownValues.isEmpty ? undefined : breakdownValues.breakdown_value.join(', '),
                label: step.name,
                seriesId: step.order,
            })
        },
        openPersonsModalForSeries: ({ step, series, converted }) => {
            // Version of openPersonsModalForStep that accurately handles breakdown series
            const breakdownValues = getBreakdownStepValues(series, series.order)
            personsModalLogic.actions.loadPeopleFromUrl({
                url: converted ? series.converted_people_url : series.dropped_people_url,
                // NOTE: although we have the url that contains all of the info needed
                // to return people, we currently still need to pass something in for the
                // purpose of the modal displaying the label.
                funnelStep: converted ? step.order + 1 : -(step.order + 1),
                breakdown_value: breakdownValues.isEmpty ? undefined : breakdownValues.breakdown_value.join(', '),
                label: step.name,
                seriesId: step.order,
            })
        },
        openCorrelationPersonsModal: ({ correlation, success }) => {
            if (correlation.result_type === FunnelCorrelationResultsType.Properties) {
                const { breakdown, breakdown_value } = parseBreakdownValue(correlation.event.event)
                personsModalLogic.actions.loadPeopleFromUrl({
                    url: success ? correlation.success_people_url : correlation.failure_people_url,
                    // just display that we either completed the last step, or
                    // dropped at the second to last step
                    funnelStep: success ? values.stepsWithCount.length : -2,
                    label: breakdown,
                    breakdown_value,
                    date_from: '',
                })

                eventUsageLogic.actions.reportCorrelationInteraction(
                    FunnelCorrelationResultsType.Properties,
                    'person modal',
                    values.filters.funnel_correlation_person_entity
                )
            } else {
                const { name, properties } = parseEventAndProperty(correlation.event)

                personsModalLogic.actions.loadPeopleFromUrl({
                    url: success ? correlation.success_people_url : correlation.failure_people_url,
                    funnelStep: success ? values.stepsWithCount.length : -2,
                    label: name,
                    date_from: '',
                })

                eventUsageLogic.actions.reportCorrelationInteraction(correlation.result_type, 'person modal', {
                    id: name,
                    type: EntityTypes.EVENTS,
                    properties,
                    converted: success,
                })
            }
        },
        changeStepRange: ({ funnel_from_step, funnel_to_step }) => {
            actions.setFilters({
                funnel_from_step,
                funnel_to_step,
            })
        },
        setBinCount: async ({ binCount }) => {
            actions.setFilters({ bin_count: binCount && binCount !== BIN_COUNT_AUTO ? binCount : undefined })
        },
        setConversionWindow: async () => {
            actions.setFilters(values.conversionWindow)
        },
        toggleAdvancedMode: () => {
            actions.setFilters({ funnel_advanced: !values.filters.funnel_advanced })
        },
        excludeEventPropertyFromProject: async ({ propertyName }) => {
            appendToCorrelationConfig('excluded_event_property_names', values.excludedEventPropertyNames, propertyName)

            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.EventWithProperties,
                'exclude event property',
                {
                    property_name: propertyName,
                }
            )
        },
        excludeEventFromProject: async ({ eventName }) => {
            appendToCorrelationConfig('excluded_event_names', values.excludedEventNames, eventName)

            eventUsageLogic.actions.reportCorrelationInteraction(FunnelCorrelationResultsType.Events, 'exclude event', {
                event_name: eventName,
            })
        },
        excludePropertyFromProject: ({ propertyName }) => {
            appendToCorrelationConfig('excluded_person_property_names', values.excludedPropertyNames, propertyName)

            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Events,
                'exclude person property',
                {
                    person_property: propertyName,
                }
            )
        },
        hideSkewWarning: () => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Events,
                'hide skew warning'
            )
        },
        setCorrelationTypes: ({ types }) => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Events,
                'set correlation types',
                { types }
            )
        },
        setPropertyCorrelationTypes: ({ types }) => {
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Properties,
                'set property correlation types',
                { types }
            )
        },
        setPropertyNames: async ({ propertyNames }) => {
            actions.loadPropertyCorrelations({})
            eventUsageLogic.actions.reportCorrelationInteraction(
                FunnelCorrelationResultsType.Properties,
                'set property names',
                { property_names: propertyNames.length === values.allProperties.length ? '$all' : propertyNames }
            )
        },
        sendCorrelationAnalysisFeedback: () => {
            eventUsageLogic.actions.reportCorrelationAnalysisDetailedFeedback(
                values.correlationFeedbackRating,
                values.correlationDetailedFeedback
            )
            actions.setCorrelationFeedbackRating(0)
            actions.setCorrelationDetailedFeedback('')
            lemonToast.success('Thanks for your feedback! Your comments help us improve')
        },
        setCorrelationFeedbackRating: ({ rating }) => {
            const feedbackBoxVisible = rating > 0
            actions.setCorrelationDetailedFeedbackVisible(feedbackBoxVisible)
            if (feedbackBoxVisible) {
                // Don't send event when resetting reducer
                eventUsageLogic.actions.reportCorrelationAnalysisFeedback(rating)
            }
        },
        [visibilitySensorLogic({ id: values.correlationPropKey }).actionTypes.setVisible]: async (
            {
                visible,
            }: {
                visible: boolean
            },
            breakpoint: BreakPointFunction
        ) => {
            if (visible && values.correlationAnalysisAvailable && values.shouldReportCorrelationViewed) {
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 0)
                await breakpoint(10000)
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 10)
            }
        },

        [visibilitySensorLogic({ id: `${values.correlationPropKey}-properties` }).actionTypes.setVisible]: async (
            {
                visible,
            }: {
                visible: boolean
            },
            breakpoint: BreakPointFunction
        ) => {
            if (visible && values.correlationAnalysisAvailable && values.shouldReportPropertyCorrelationViewed) {
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 0, true)
                await breakpoint(10000)
                eventUsageLogic.actions.reportCorrelationViewed(values.filters, 10, true)
            }
        },
    }),
})

const appendToCorrelationConfig = (
    configKey: keyof TeamType['correlation_config'],
    currentValue: string[],
    configValue: string
): void => {
    // Helper to handle updating correlationConfig within the Team model. Only
    // handles further appending to current values.

    // When we exclude a property, we want to update the config stored
    // on the current Team/Project.
    const oldCurrentTeam = teamLogic.values.currentTeam

    // If we haven't actually retrieved the current team, we can't
    // update the config.
    if (oldCurrentTeam === null || !currentValue) {
        console.warn('Attempt to update correlation config without first retrieving existing config')
        return
    }

    const oldCorrelationConfig = oldCurrentTeam.correlation_config

    const configList = [...Array.from(new Set(currentValue.concat([configValue])))]

    const correlationConfig = {
        ...oldCorrelationConfig,
        [configKey]: configList,
    }

    teamLogic.actions.updateCurrentTeam({
        correlation_config: correlationConfig,
    })
}

const parseBreakdownValue = (
    item: string
): {
    breakdown: string
    breakdown_value: string
} => {
    const components = item.split('::')
    if (components.length === 1) {
        return { breakdown: components[0], breakdown_value: '' }
    } else {
        return {
            breakdown: components[0],
            breakdown_value: components[1],
        }
    }
}

const parseEventAndProperty = (
    event: FunnelCorrelation['event']
): {
    name: string
    properties?: PropertyFilter[]
} => {
    const components = event.event.split('::')
    /*
      The `event` is either an event name, or event::property::property_value
    */
    if (components.length === 1) {
        return { name: components[0] }
    } else if (components[0] === '$autocapture') {
        // We use elementsToAction to generate the required property filters
        const elementData = elementsToAction(event.elements)
        return {
            name: components[0],
            properties: Object.entries(elementData)
                .filter(([, propertyValue]) => !!propertyValue)
                .map(([propertyKey, propertyValue]) => ({
                    key: propertyKey,
                    operator: PropertyOperator.Exact,
                    type: 'element',
                    value: [propertyValue as string],
                })),
        }
    } else {
        return {
            name: components[0],
            properties: [{ key: components[1], operator: PropertyOperator.Exact, value: components[2], type: 'event' }],
        }
    }
}
