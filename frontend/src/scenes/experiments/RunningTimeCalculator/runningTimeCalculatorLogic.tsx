import equal from 'fast-deep-equal'
import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DEFAULT_MDE } from 'scenes/experiments/experimentLogic'

import { performQuery } from '~/queries/query'
import {
    ExperimentMetric,
    FunnelsQuery,
    TrendsQuery,
    TrendsQueryResponse,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
} from '~/queries/schema/schema-general'
import {
    addExposureToQuery,
    compose,
    getDefaultDateRange,
    getEventNode,
    getQuery,
} from '~/scenes/experiments/metricQueryUtils'
import { AnyPropertyFilter, BaseMathType, Experiment, ExperimentMetricMathType, FunnelVizType } from '~/types'

import { calculateRecommendedSampleSize, calculateVariance } from './experimentStatisticsUtils'
import type { runningTimeCalculatorLogicType } from './runningTimeCalculatorLogicType'

export const TIMEFRAME_HISTORICAL_DATA_DAYS = 14
export const VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
export const VARIANCE_SCALING_FACTOR_SUM = 0.25

export enum ConversionRateInputType {
    MANUAL = 'manual',
    AUTOMATIC = 'automatic',
}

export interface RunningTimeCalculatorLogicProps {
    experiment: Experiment
}

export interface ExposureEstimateConfig {
    /**
     * This is the filter for the first step of the funnel for estimation purposes.
     * It is not used for the funnel query. Instead, typically we'll use a $feature_flag event.
     */
    eventFilter: EventConfig | null
    metric: ExperimentMetric | null
    conversionRateInputType: ConversionRateInputType
    manualConversionRate: number | null
    uniqueUsers: number | null
}

/** TODO: this is not a great name for this type, but we'll change it later. */
export interface EventConfig {
    event: string
    name: string
    properties: AnyPropertyFilter[]
    entityType: TaxonomicFilterGroupType.Events | TaxonomicFilterGroupType.Actions
}

const defaultExposureEstimateConfig: ExposureEstimateConfig = {
    eventFilter: {
        event: '$pageview',
        name: '$pageview',
        properties: [],
        entityType: TaxonomicFilterGroupType.Events,
    },
    metric: null as ExperimentMetric | null,
    conversionRateInputType: ConversionRateInputType.AUTOMATIC,
    manualConversionRate: 2,
    uniqueUsers: null,
}

export const runningTimeCalculatorLogic = kea<runningTimeCalculatorLogicType>([
    path(['scenes', 'experiments', 'RunningTimeCalculator', 'runningTimeCalculatorLogic']),
    props({} as RunningTimeCalculatorLogicProps),
    actions({
        setMetricIndex: (value: number) => ({ value }),
        setMetricUuid: (value: string) => ({ value }),
        setMetricResult: (value: {
            uniqueUsers: number
            averageEventsPerUser?: number
            averagePropertyValuePerUser?: number
            automaticConversionRateDecimal?: number
        }) => ({ value }),
        setConversionRateInputType: (value: string) => ({ value }),
        setManualConversionRate: (value: number) => ({ value }),
        setExposureEstimateConfig: (value: ExposureEstimateConfig) => ({ value }),
        setMinimumDetectableEffect: (value: number) => ({ value }),
    }),
    reducers({
        _exposureEstimateConfig: [
            null as ExposureEstimateConfig | null,
            { setExposureEstimateConfig: (_, { value }) => value },
        ],
        _metricUuid: [
            null as string | null,
            {
                setMetricUuid: (_, { value }) => value,
            },
        ],
        _conversionRateInputType: [
            ConversionRateInputType.AUTOMATIC as string,
            { setConversionRateInputType: (_, { value }) => value },
        ],
        _manualConversionRate: [2 as number, { setManualConversionRate: (_, { value }) => value }],
        _minimumDetectableEffect: [null as number | null, { setMinimumDetectableEffect: (_, { value }) => value }],
    }),
    loaders(({ values, props }) => ({
        metricResult: {
            loadMetricResult: async () => {
                if (values.metricUuid === null) {
                    return null
                }

                const metric = values.metric as ExperimentMetric

                if (!metric) {
                    return null
                }

                /**
                 * we get the event filter from the exposure estimate config, or use
                 * $pageview as the default.
                 */
                const eventFilter = values.exposureEstimateConfig?.eventFilter ?? {
                    event: '$pageview',
                    name: '$pageview',
                    properties: [],
                    entityType: TaxonomicFilterGroupType.Events,
                }
                /**
                 * we create the exposure event node and add math properties to it
                 */
                const exposureEventNode = getEventNode(eventFilter, {
                    mathProps: {
                        math: BaseMathType.UniqueUsers,
                    },
                })

                /**
                 * let's compose a query builder that will take a metric and return a query
                 * with all the options we need for running time calculations.
                 */
                const queryBuilder = compose<
                    ExperimentMetric,
                    FunnelsQuery | TrendsQuery | undefined,
                    FunnelsQuery | TrendsQuery | undefined
                >(
                    getQuery({
                        filterTestAccounts: !!props.experiment.exposure_criteria?.filterTestAccounts,
                        dateRange: getDefaultDateRange(),
                        funnelsFilter: {
                            funnelVizType: FunnelVizType.Steps,
                        },
                        trendsFilter: {},
                    }),
                    addExposureToQuery(exposureEventNode)
                )

                const query = queryBuilder(metric)

                if (!query) {
                    return null
                }

                const result = (await performQuery(query, undefined, 'force_blocking')) as Partial<TrendsQueryResponse>

                if (isExperimentMeanMetric(metric)) {
                    return {
                        uniqueUsers: result?.results?.[0]?.count ?? null,
                        ...(metric.source.math === ExperimentMetricMathType.TotalCount
                            ? { averageEventsPerUser: result?.results?.[1]?.count ?? null }
                            : {}),
                        ...(metric.source.math === ExperimentMetricMathType.Sum
                            ? { averagePropertyValuePerUser: result?.results?.[1]?.count ?? null }
                            : {}),
                    }
                }

                if (isExperimentFunnelMetric(metric)) {
                    const firstStepCount = result?.results?.[0]?.count
                    const automaticConversionRateDecimal =
                        firstStepCount && firstStepCount > 0
                            ? (result?.results?.at(-1)?.count || 0) / firstStepCount
                            : null

                    return {
                        uniqueUsers: result?.results?.[0]?.count ?? null,
                        automaticConversionRateDecimal: automaticConversionRateDecimal,
                    }
                }

                return {}
            },
            // For testing purposes, we want to be able set the metric result directly
            setMetricResult: ({ value }) => value,
        },
    })),
    listeners(({ actions, values, props }) => ({
        setMetricIndex: ({ value: metricIndex }) => {
            // Convert index to UUID and set it
            const metric = props.experiment.metrics?.[metricIndex]
            if (metric?.uuid) {
                actions.setMetricUuid(metric.uuid)
            }
        },
        setMetricUuid: () => {
            // When metric UUID changes, update exposure estimate config with the new metric
            if (values.metric) {
                actions.setExposureEstimateConfig({
                    ...(values.exposureEstimateConfig ?? defaultExposureEstimateConfig),
                    metric: values.metric,
                })
            }
            actions.loadMetricResult()
        },
        setManualConversionRate: () => {
            /**
             * We listen for changes in the manual conversion rate and update the exposure estimate config
             */
            actions.setExposureEstimateConfig({
                ...(values.exposureEstimateConfig ?? {
                    eventFilter: null,
                    metric: null,
                    conversionRateInputType: ConversionRateInputType.MANUAL,
                    uniqueUsers: null,
                }),
                manualConversionRate: values._manualConversionRate,
            })
        },
        loadMetricResultSuccess: () => {
            /**
             * We listen for changes in the metric results.
             * If the unique users have changed, we update the exposure estimate config.
             * Otherwise, this could cause an infinite loop, because changing the exposure estimate config
             * could trigger a change in the metric result.
             */
            const uniqueUsers = values.metricResult?.uniqueUsers
            if (uniqueUsers !== values.exposureEstimateConfig?.uniqueUsers) {
                actions.setExposureEstimateConfig({
                    ...(values.exposureEstimateConfig ?? {
                        eventFilter: null,
                        metric: null,
                        conversionRateInputType: ConversionRateInputType.AUTOMATIC,
                        manualConversionRate: null,
                    }),
                    uniqueUsers,
                })
            }
        },
    })),
    afterMount(({ actions, values }) => {
        // Initial calculation if we have a valid metric selected and no metric result yet
        if (values.metric && !values.metricResult && values.metricUuid !== null) {
            actions.loadMetricResult()
        }
    }),
    selectors({
        defaultMetricUuid: [
            (s) => [(_, props) => props.experiment, s.exposureEstimateConfig],
            (experiment: Experiment, exposureEstimateConfig: ExposureEstimateConfig | null): string | null => {
                if (!experiment.metrics || !exposureEstimateConfig?.metric) {
                    return null
                }

                // First check regular metrics
                const regularMetric = experiment.metrics.find((m) => equal(m, exposureEstimateConfig.metric))
                if (regularMetric?.uuid) {
                    return regularMetric.uuid
                }

                // If not found, check shared metrics
                const primarySharedMetrics = experiment.saved_metrics.filter((m) => m.metadata.type === 'primary')
                const sharedMetric = primarySharedMetrics.find((m) => equal(m.query, exposureEstimateConfig.metric))

                return sharedMetric?.query?.uuid || null
            },
        ],
        metricUuid: [
            (s) => [s._metricUuid, s.defaultMetricUuid],
            (metricUuid: string | null, defaultMetricUuid: string | null): string | null => {
                // If metricUuid was manually set, use that
                // Otherwise use the default from exposureEstimateConfig if available
                return metricUuid ?? defaultMetricUuid
            },
        ],
        exposureEstimateConfig: [
            (s) => [s._exposureEstimateConfig, (_, props) => props.experiment],
            (
                localExposureEstimateConfig: ExposureEstimateConfig | null,
                experiment: Experiment
            ): ExposureEstimateConfig | null => {
                // If we have a "local" state, use that
                if (localExposureEstimateConfig) {
                    return localExposureEstimateConfig
                }

                // If we don't have a "local" state, use the exposure estimate config saved in the experiment parameters
                // In case of not having all of the fields, we use the default exposure estimate config
                if (experiment.parameters?.exposure_estimate_config) {
                    return {
                        ...defaultExposureEstimateConfig,
                        ...experiment.parameters.exposure_estimate_config,
                    }
                }

                // Otherwise, use the default exposure estimate config
                return defaultExposureEstimateConfig
            },
        ],
        conversionRateInputType: [
            (s) => [s._conversionRateInputType, s.exposureEstimateConfig],
            (conversionRateInputType: string, exposureEstimateConfig: ExposureEstimateConfig | null): string => {
                if (!conversionRateInputType) {
                    return conversionRateInputType
                }

                if (exposureEstimateConfig) {
                    return exposureEstimateConfig.conversionRateInputType
                }

                return ConversionRateInputType.AUTOMATIC
            },
        ],
        manualConversionRate: [
            (s) => [s._manualConversionRate, s.exposureEstimateConfig],
            (manualConversionRate: number, exposureEstimateConfig: ExposureEstimateConfig | null): number | null => {
                if (exposureEstimateConfig?.conversionRateInputType === ConversionRateInputType.MANUAL) {
                    return exposureEstimateConfig.manualConversionRate
                }
                return manualConversionRate
            },
        ],
        minimumDetectableEffect: [
            (s) => [s._minimumDetectableEffect, (_, props) => props.experiment],
            (minimumDetectableEffect: number | null, experiment: Experiment) =>
                minimumDetectableEffect ?? experiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE,
        ],
        metric: [
            (s) => [s.metricUuid, (_, props) => props.experiment],
            (metricUuid: string | null, experiment: Experiment): ExperimentMetric | null => {
                if (metricUuid === null) {
                    return null
                }

                // First check regular metrics
                const regularMetric = experiment.metrics.find((m) => m.uuid === metricUuid)
                if (regularMetric) {
                    return regularMetric as ExperimentMetric
                }

                // If not found, check shared metrics with primary type
                const primarySharedMetrics = experiment.saved_metrics.filter((m) => m.metadata.type === 'primary')
                const sharedMetric = primarySharedMetrics.find((m) => m.query?.uuid === metricUuid)

                return sharedMetric?.query as ExperimentMetric
            },
        ],
        uniqueUsers: [
            (s) => [s.metricResult, s.exposureEstimateConfig],
            (metricResult: { uniqueUsers: number }, exposureEstimateConfig: ExposureEstimateConfig | null) => {
                if (metricResult && metricResult.uniqueUsers !== null) {
                    return metricResult.uniqueUsers
                }

                return exposureEstimateConfig?.uniqueUsers ?? null
            },
        ],
        averageEventsPerUser: [
            (s) => [s.metricResult],
            (metricResult: { averageEventsPerUser: number }) => metricResult?.averageEventsPerUser ?? null,
        ],
        averagePropertyValuePerUser: [
            (s) => [s.metricResult],
            (metricResult: { averagePropertyValuePerUser: number }) =>
                metricResult?.averagePropertyValuePerUser ?? null,
        ],
        automaticConversionRateDecimal: [
            (s) => [s.metricResult],
            (metricResult: { automaticConversionRateDecimal: number }) =>
                metricResult?.automaticConversionRateDecimal ?? null,
        ],
        variance: [
            (s) => [s.metric, s.averageEventsPerUser, s.averagePropertyValuePerUser],
            (metric: ExperimentMetric, averageEventsPerUser: number, averagePropertyValuePerUser: number) =>
                /**
                 * we need this to satify kea's typegen.
                 * Do not despair, this will be removed.
                 */
                calculateVariance(metric, averageEventsPerUser, averagePropertyValuePerUser),
        ],
        standardDeviation: [(s) => [s.variance], (variance: number) => (variance ? Math.sqrt(variance) : null)],
        numberOfVariants: [
            () => [(_, props) => props.experiment],
            (experiment: Experiment) => experiment.feature_flag?.filters.multivariate?.variants.length,
        ],
        recommendedSampleSize: [
            (s) => [
                s.metric,
                s.minimumDetectableEffect,
                s.variance,
                s.averageEventsPerUser,
                s.averagePropertyValuePerUser,
                s.automaticConversionRateDecimal,
                s.manualConversionRate,
                s.conversionRateInputType,
                s.numberOfVariants,
            ],
            (
                metric: ExperimentMetric,
                minimumDetectableEffect: number,
                variance: number,
                averageEventsPerUser: number,
                averagePropertyValuePerUser: number,
                automaticConversionRateDecimal: number,
                manualConversionRate: number,
                conversionRateInputType: string,
                numberOfVariants: number
            ): number | null =>
                /**
                 * we need this to satify kea's typegen.
                 * Do not despair, this will be removed.
                 */
                calculateRecommendedSampleSize(
                    metric,
                    minimumDetectableEffect,
                    variance,
                    averageEventsPerUser,
                    averagePropertyValuePerUser,
                    automaticConversionRateDecimal,
                    manualConversionRate,
                    conversionRateInputType as ConversionRateInputType,
                    numberOfVariants
                ),
        ],
        recommendedRunningTime: [
            (s) => [s.recommendedSampleSize, s.uniqueUsers],
            (recommendedSampleSize: number, uniqueUsers: number): number => {
                return recommendedSampleSize / (uniqueUsers / TIMEFRAME_HISTORICAL_DATA_DAYS)
            },
        ],
    }),
])
