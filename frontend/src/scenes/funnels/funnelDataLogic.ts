import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { DataColorTheme, DataColorToken } from 'lib/colors'
import { BIN_COUNT_AUTO } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { average, percentage, sum } from 'lib/utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { getColorFromToken } from 'scenes/dataThemeLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getFunnelDatasetKey, getFunnelResultCustomizationColorToken } from 'scenes/insights/utils'

import { Noun, groupsModel } from '~/models/groupsModel'
import { FunnelsFilter, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { isFunnelsQuery } from '~/queries/utils'
import {
    FlattenedFunnelStepByBreakdown,
    FunnelAPIResponse,
    FunnelConversionWindow,
    FunnelConversionWindowTimeUnit,
    FunnelResultType,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    FunnelTimeConversionMetrics,
    FunnelVizType,
    FunnelsTimeConversionBins,
    HistogramGraphDatum,
    InsightLogicProps,
    InsightType,
    StepOrderValue,
    TrendResult,
} from '~/types'

import type { funnelDataLogicType } from './funnelDataLogicType'
import {
    aggregateBreakdownResult,
    aggregationLabelForHogQL,
    flattenedStepsByBreakdown,
    getIncompleteConversionWindowStartDate,
    getLastFilledStep,
    getReferenceStep,
    getVisibilityKey,
    isBreakdownFunnelResults,
    stepsWithConversionMetrics,
} from './funnelUtils'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

export const funnelDataLogic = kea<funnelDataLogicType>([
    path((key) => ['scenes', 'funnels', 'funnelDataLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            [
                'querySource as vizQuerySource',
                'insightFilter',
                'funnelsFilter',
                'breakdownFilter',
                'goalLines',
                'series',
                'interval',
                'insightData',
                'insightDataError',
                'getTheme',
                'showValuesOnSeries',
            ],
            groupsModel,
            ['aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter', 'updateQuerySource']],
    })),

    actions({
        hideSkewWarning: true,
        setHiddenLegendBreakdowns: (hiddenLegendBreakdowns: string[]) => ({ hiddenLegendBreakdowns }),
        toggleLegendBreakdownVisibility: (breakdown: string) => ({ breakdown }),
        setBreakdownSortOrder: (breakdownSortOrder: (string | number)[]) => ({ breakdownSortOrder }),
    }),

    reducers({
        skewWarningHidden: [
            false,
            {
                hideSkewWarning: () => true,
            },
        ],
        breakdownSortOrder: [
            [] as (string | number)[],
            {
                setBreakdownSortOrder: (_, { breakdownSortOrder }) => breakdownSortOrder,
            },
        ],
    }),

    selectors(({ props }) => ({
        querySource: [
            (s) => [s.vizQuerySource],
            (vizQuerySource) => (isFunnelsQuery(vizQuerySource) ? vizQuerySource : null),
        ],

        isStepsFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null
                    ? null
                    : funnelsFilter === undefined
                      ? true
                      : funnelsFilter.funnelVizType === FunnelVizType.Steps
            },
        ],
        isTimeToConvertFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null ? null : funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert
            },
        ],
        isTrendsFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null ? null : funnelsFilter?.funnelVizType === FunnelVizType.Trends
            },
        ],

        isEmptyFunnel: [
            (s) => [s.querySource],
            (q): boolean | null => {
                return isFunnelsQuery(q)
                    ? q.series.filter((n) => n.kind === NodeKind.EventsNode || n.kind === NodeKind.ActionsNode)
                          .length === 0
                    : null
            },
        ],

        aggregationTargetLabel: [
            (s) => [s.querySource, s.aggregationLabel],
            (querySource, aggregationLabel): Noun => {
                if (!querySource) {
                    return { singular: '', plural: '' }
                }

                return querySource.funnelsFilter?.funnelAggregateByHogQL
                    ? aggregationLabelForHogQL(querySource.funnelsFilter.funnelAggregateByHogQL)
                    : aggregationLabel(querySource.aggregation_group_type_index)
            },
        ],

        results: [
            (s) => [s.insightData],
            (insightData: FunnelAPIResponse | null): FunnelResultType => {
                // TODO: after hooking up data manager, check that we have a funnels result here
                if (insightData?.result) {
                    if (isBreakdownFunnelResults(insightData.result) && insightData.result?.[0]?.[0]?.breakdowns) {
                        // in order to stop the UI having to check breakdowns and breakdown
                        // this collapses breakdowns onto the breakdown property
                        return insightData.result.map((series) =>
                            series.map((step) => {
                                const { breakdowns, ...clone } = step
                                clone.breakdown = breakdowns as (string | number)[]
                                return clone
                            })
                        )
                    }
                    return insightData.result
                }
                return []
            },
        ],
        steps: [
            (s) => [s.insightData, s.querySource, s.breakdownFilter, s.results, s.isTimeToConvertFunnel],
            (
                insightData,
                querySource,
                breakdownFilter,
                results,
                isTimeToConvertFunnel
            ): FunnelStepWithNestedBreakdown[] => {
                if (
                    // TODO: Ideally we don't check filters anymore, but tests are still using this
                    insightData?.filters?.insight !== InsightType.FUNNELS &&
                    querySource &&
                    querySource?.kind !== NodeKind.FunnelsQuery
                ) {
                    return []
                }

                // we need to check wether results are an array, since isTimeToConvertFunnel can be false,
                // while still having "time-to-convert" results in insightData
                if (!isTimeToConvertFunnel && Array.isArray(results)) {
                    if (isBreakdownFunnelResults(results)) {
                        const breakdownProperty = breakdownFilter?.breakdowns
                            ? breakdownFilter?.breakdowns.map((b) => b.property).join('::')
                            : (breakdownFilter?.breakdown ?? undefined)
                        return aggregateBreakdownResult(results, breakdownProperty).sort((a, b) => a.order - b.order)
                    }
                    return results.sort((a, b) => a.order - b.order)
                }
                return []
            },
        ],
        stepsWithConversionMetrics: [
            (s) => [s.steps, s.funnelsFilter, s.querySource],
            (
                steps: FunnelStepWithNestedBreakdown[],
                funnelsFilter: FunnelsFilter | null,
                querySource: FunnelsQuery | null
            ): FunnelStepWithConversionMetrics[] => {
                const stepReference = funnelsFilter?.funnelStepReference || FunnelStepReference.total
                // Get optional steps from series (1-indexed)
                const optionalSteps =
                    querySource?.kind === NodeKind.FunnelsQuery
                        ? querySource.series
                              .map((_, i: number) => i + 1)
                              .filter((_: number, i: number) => querySource.series[i]?.optionalInFunnel)
                        : []
                return stepsWithConversionMetrics(steps, stepReference, optionalSteps)
            },
        ],

        // hack for experiments to remove displaying baseline from the funnel viz
        disableFunnelBreakdownBaseline: [
            () => [(_, props) => props],
            (props: InsightLogicProps): boolean => !!props.cachedInsight?.disable_baseline,
        ],
        flattenedBreakdowns: [
            (s) => [s.stepsWithConversionMetrics, s.funnelsFilter, s.disableFunnelBreakdownBaseline],
            (steps, funnelsFilter, disableBaseline): FlattenedFunnelStepByBreakdown[] => {
                return flattenedStepsByBreakdown(steps, funnelsFilter?.layout, disableBaseline, true)
            },
        ],
        hiddenLegendBreakdowns: [(s) => [s.funnelsFilter], (funnelsFilter) => funnelsFilter?.hiddenLegendBreakdowns],
        resultCustomizations: [(s) => [s.funnelsFilter], (funnelsFilter) => funnelsFilter?.resultCustomizations],
        visibleStepsWithConversionMetrics: [
            (s) => [
                s.stepsWithConversionMetrics,
                s.flattenedBreakdowns,
                s.breakdownSortOrder,
                s.hiddenLegendBreakdowns,
            ],
            (
                steps: FunnelStepWithConversionMetrics[],
                flattenedBreakdowns: FlattenedFunnelStepByBreakdown[],
                breakdownSortOrder: (string | number)[],
                hiddenLegendBreakdowns: string[]
            ): FunnelStepWithConversionMetrics[] => {
                const isOnlySeries = flattenedBreakdowns.length <= 1
                const baseLineSteps = flattenedBreakdowns.find((b) => b.isBaseline)
                return steps.map((step, stepIndex) => {
                    let nested = (
                        baseLineSteps?.steps
                            ? [baseLineSteps.steps[stepIndex], ...(step?.nested_breakdown ?? [])]
                            : step?.nested_breakdown
                    )
                        ?.map((b, breakdownIndex) => ({
                            ...b,
                            order: breakdownIndex,
                        }))
                        ?.filter(
                            (b) =>
                                isOnlySeries || !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
                        )
                    // Sort by breakdownSortOrder if present
                    if (breakdownSortOrder && breakdownSortOrder.length > 0 && nested) {
                        nested = [...nested].sort((a, b) => {
                            const aValue = Array.isArray(a.breakdown_value) ? a.breakdown_value[0] : a.breakdown_value
                            const bValue = Array.isArray(b.breakdown_value) ? b.breakdown_value[0] : b.breakdown_value
                            return breakdownSortOrder.indexOf(aValue ?? '') - breakdownSortOrder.indexOf(bValue ?? '')
                        })
                    }
                    return {
                        ...step,
                        nested_breakdown: nested,
                    }
                })
            },
        ],

        /*
         * Time-to-convert funnels
         */
        timeConversionResults: [
            (s) => [s.results, s.funnelsFilter],
            (results, funnelsFilter): FunnelsTimeConversionBins | null => {
                return funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert
                    ? (results as FunnelsTimeConversionBins)
                    : null
            },
        ],
        histogramGraphData: [
            (s) => [s.timeConversionResults],
            (timeConversionResults: FunnelsTimeConversionBins): HistogramGraphDatum[] | null => {
                if ((timeConversionResults?.bins?.length ?? 0) < 2) {
                    return null // There are no results
                }

                const totalCount = sum(timeConversionResults.bins.map(([, count]) => count))
                if (totalCount === 0) {
                    return [] // Nobody has converted in the time period
                }

                const binSize = timeConversionResults.bins[1][0] - timeConversionResults.bins[0][0]
                return timeConversionResults.bins.map(([id, count]: [id: number, count: number]) => {
                    const value = Math.max(0, id)
                    const percent = totalCount === 0 ? 0 : count / totalCount
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
        hasFunnelResults: [
            (s) => [s.insightData, s.funnelsFilter, s.steps, s.histogramGraphData, s.querySource],
            (insightData, funnelsFilter, steps, histogramGraphData, querySource) => {
                if (
                    // TODO: Ideally we don't check filters anymore, but tests are still using this
                    insightData?.filters?.insight !== InsightType.FUNNELS &&
                    querySource &&
                    querySource?.kind !== NodeKind.FunnelsQuery
                ) {
                    return false
                }

                if (funnelsFilter?.funnelVizType === FunnelVizType.Steps || !funnelsFilter?.funnelVizType) {
                    return !!(steps && steps[0] && steps[0].count > -1)
                } else if (funnelsFilter.funnelVizType === FunnelVizType.TimeToConvert) {
                    return (histogramGraphData?.length ?? 0) > 0
                } else if (funnelsFilter.funnelVizType === FunnelVizType.Trends) {
                    return (steps?.length ?? 0) > 0 && !!steps?.[0]?.labels
                }
                return false
            },
        ],
        numericBinCount: [
            (s) => [s.funnelsFilter, s.timeConversionResults],
            (funnelsFilter, timeConversionResults): number => {
                if (funnelsFilter?.binCount === BIN_COUNT_AUTO) {
                    return timeConversionResults?.bins?.length ?? 0
                }
                return funnelsFilter?.binCount ?? 0
            },
        ],

        conversionMetrics: [
            (s) => [s.steps, s.funnelsFilter, s.timeConversionResults],
            (steps, funnelsFilter, timeConversionResults): FunnelTimeConversionMetrics => {
                // steps should be empty in time conversion view. Return metrics precalculated on backend
                if (funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert) {
                    return {
                        averageTime: timeConversionResults?.average_conversion_time ?? 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                // Handle metrics for trends
                if (funnelsFilter?.funnelVizType === FunnelVizType.Trends) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: average((steps?.[0] as unknown as TrendResult)?.data ?? []) / 100,
                    }
                }

                // Handle metrics for steps
                // no concept of funnel_from_step and funnel_to_step here
                if (steps.length <= 1) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                const toStep = getLastFilledStep(steps)
                const fromStep = getReferenceStep(steps, FunnelStepReference.total)

                return {
                    averageTime: steps.reduce(
                        (conversion_time, step) => conversion_time + (step.average_conversion_time || 0),
                        0
                    ),
                    stepRate: fromStep.count === 0 ? 0 : toStep.count / fromStep.count,
                    totalRate: steps[0].count === 0 ? 0 : steps[steps.length - 1].count / steps[0].count,
                }
            },
        ],
        conversionWindow: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): FunnelConversionWindow => {
                const { funnelWindowInterval, funnelWindowIntervalUnit } = funnelsFilter || {}
                return {
                    funnelWindowInterval: funnelWindowInterval || 14,
                    funnelWindowIntervalUnit: funnelWindowIntervalUnit || FunnelConversionWindowTimeUnit.Day,
                }
            },
        ],
        incompletenessOffsetFromEnd: [
            (s) => [s.steps, s.conversionWindow],
            (steps, conversionWindow) => {
                if (steps?.[0]?.days === undefined) {
                    return 0
                }

                // subtract conversion window from today and look for a matching day
                const startDate = getIncompleteConversionWindowStartDate(conversionWindow)
                const startIndex = steps[0].days.findIndex((day) => dayjs(day) >= startDate)

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - steps[0].days.length
                }
                return 0
            },
        ],

        /*
         * Advanced options: funnelOrderType, funnelStepReference, exclusions
         */
        advancedOptionsUsedCount: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): number => {
                let count = 0
                if (funnelsFilter?.funnelOrderType && funnelsFilter?.funnelOrderType !== StepOrderValue.ORDERED) {
                    count = count + 1
                }
                if (
                    funnelsFilter?.funnelStepReference &&
                    funnelsFilter?.funnelStepReference !== FunnelStepReference.total
                ) {
                    count = count + 1
                }
                if (funnelsFilter?.exclusions?.length) {
                    count = count + 1
                }
                return count
            },
        ],

        isSkewed: [
            (s) => [s.conversionMetrics, s.skewWarningHidden],
            (conversionMetrics, skewWarningHidden): boolean => {
                return !skewWarningHidden && (conversionMetrics.totalRate < 0.1 || conversionMetrics.totalRate > 0.9)
            },
        ],
        indexedSteps: [
            (s) => [s.steps],
            (steps) =>
                Array.isArray(steps) ? steps.map((step, index) => ({ ...step, seriesIndex: index, id: index })) : [],
        ],
        getFunnelsColorToken: [
            (s) => [s.resultCustomizations, s.getTheme, s.breakdownFilter, s.querySource],
            (resultCustomizations, getTheme, breakdownFilter, querySource) => {
                return (
                    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
                ): [DataColorTheme | null, DataColorToken | null] => {
                    // stringified breakdown value
                    const key = getFunnelDatasetKey(dataset)
                    let breakdownValue = JSON.parse(key)['breakdown_value']
                    breakdownValue = Array.isArray(breakdownValue) ? breakdownValue.join('::') : breakdownValue

                    // dashboard color overrides
                    const logic = dashboardLogic.findMounted({ id: props.dashboardId })
                    const dashboardBreakdownColors = logic?.values.temporaryBreakdownColors
                    const colorOverride = dashboardBreakdownColors?.find(
                        (config) =>
                            config.breakdownValue === breakdownValue &&
                            config.breakdownType === (breakdownFilter?.breakdown_type ?? 'event')
                    )

                    if (colorOverride?.colorToken) {
                        // use the dashboard theme, or fallback to the default theme
                        const dashboardTheme = logic?.values.dataColorTheme || getTheme(undefined)
                        return [dashboardTheme, colorOverride.colorToken]
                    }

                    // use the dashboard theme, or fallback to the insight theme, or the default theme
                    const theme = logic?.values.dataColorTheme || getTheme(querySource?.dataColorTheme)
                    if (!theme) {
                        return [null, null]
                    }

                    return [
                        theme,
                        getFunnelResultCustomizationColorToken(
                            resultCustomizations,
                            theme,
                            dataset,
                            props?.cachedInsight?.disable_baseline
                        ),
                    ]
                }
            },
        ],
        getFunnelsColor: [
            (s) => [s.getFunnelsColorToken],
            (getFunnelsColorToken) => {
                return (dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics) => {
                    const [colorTheme, colorToken] = getFunnelsColorToken(dataset)
                    return colorTheme && colorToken ? getColorFromToken(colorTheme, colorToken) : '#000000'
                }
            },
        ],
        isStepOptional: [
            (s) => [s.querySource],
            (querySource: FunnelsQuery | null) => {
                return (step: number) => {
                    if (querySource?.kind === NodeKind.FunnelsQuery) {
                        // step is 1-indexed, series is 0-indexed
                        return querySource.series[step - 1]?.optionalInFunnel === true
                    }
                    return false
                }
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        setHiddenLegendBreakdowns: ({ hiddenLegendBreakdowns }) => {
            actions.updateInsightFilter({ hiddenLegendBreakdowns })
        },
        toggleLegendBreakdownVisibility: ({ breakdown }) => {
            values.hiddenLegendBreakdowns?.includes(breakdown)
                ? actions.setHiddenLegendBreakdowns(values.hiddenLegendBreakdowns.filter((b) => b !== breakdown))
                : actions.setHiddenLegendBreakdowns([...(values.hiddenLegendBreakdowns || []), breakdown])
        },
    })),
])
