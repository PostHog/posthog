import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { DEFAULT_MDE, experimentLogic } from 'scenes/experiments/experimentLogic'

import { performQuery } from '~/queries/query'
import {
    ExperimentMetric,
    ExperimentMetricType,
    FunnelsQuery,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    NodeKind,
    TrendsQuery,
    TrendsQueryResponse,
} from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    CountPerActorMathType,
    Experiment,
    ExperimentMetricMathType,
    FunnelVizType,
    PropertyMathType,
} from '~/types'

import type { runningTimeCalculatorLogicType } from './runningTimeCalculatorLogicType'

export const TIMEFRAME_HISTORICAL_DATA_DAYS = 14
export const VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
export const VARIANCE_SCALING_FACTOR_SUM = 0.25

export enum ConversionRateInputType {
    MANUAL = 'manual',
    AUTOMATIC = 'automatic',
}

// Creates the correct identifier properties for a series item based on metric type
const getSeriesItemProps = (metric: ExperimentMetric): { kind: NodeKind } & Record<string, any> => {
    if (isExperimentMeanMetric(metric)) {
        const { source } = metric

        if (source.kind === NodeKind.EventsNode) {
            return {
                kind: NodeKind.EventsNode,
                event: source.event,
            }
        }

        if (source.kind === NodeKind.ActionsNode) {
            return {
                kind: NodeKind.ActionsNode,
                id: source.id,
            }
        }

        if (source.kind === NodeKind.ExperimentDataWarehouseNode) {
            return {
                kind: NodeKind.ExperimentDataWarehouseNode,
                table_name: source.table_name,
            }
        }
    }

    if (isExperimentFunnelMetric(metric)) {
        /**
         * For multivariate funnels, we select the last step
         * Although we know that the last step is always an EventsNode, TS infers that the last step might be undefined
         * so we use the non-null assertion operator (!) to tell TS that we know the last step is always an EventsNode
         */
        const step = metric.series.at(-1)!

        if (step.kind === NodeKind.EventsNode) {
            return {
                kind: NodeKind.EventsNode,
                event: step.event,
            }
        }

        if (step.kind === NodeKind.ActionsNode) {
            return {
                kind: NodeKind.ActionsNode,
                id: step.id,
            }
        }
    }

    throw new Error(`Unsupported metric type: ${metric.metric_type || 'unknown'}`)
}

const getTotalCountQuery = (
    metric: ExperimentMetric,
    experiment: Experiment,
    eventConfig: EventConfig | null
): TrendsQuery => {
    const baseProps = getSeriesItemProps(metric)

    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: eventConfig?.event ?? '$pageview',
                properties: eventConfig?.properties ?? [],
                math: BaseMathType.UniqueUsers,
            },
            {
                ...baseProps,
                math: CountPerActorMathType.Average,
            },
        ],
        trendsFilter: {},
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: {
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            explicitDate: true,
        },
    } as TrendsQuery
}

const getSumQuery = (
    metric: ExperimentMetric,
    experiment: Experiment,
    eventConfig: EventConfig | null
): TrendsQuery => {
    const baseProps = getSeriesItemProps(metric)
    const mathProperty =
        metric.metric_type === ExperimentMetricType.MEAN
            ? {
                  math_property: metric.source.math_property,
                  math_property_type: TaxonomicFilterGroupType.NumericalEventProperties,
              }
            : {}

    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: eventConfig?.event ?? '$pageview',
                properties: eventConfig?.properties ?? [],
                math: BaseMathType.UniqueUsers,
            },
            {
                ...baseProps,
                math: PropertyMathType.Sum,
                ...mathProperty,
            },
        ],
        trendsFilter: {},
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: {
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            explicitDate: true,
        },
    } as TrendsQuery
}

const getFunnelQuery = (
    metric: ExperimentMetric,
    eventConfig: EventConfig | null,
    experiment: Experiment
): FunnelsQuery => {
    const baseProps = getSeriesItemProps(metric)

    return {
        kind: NodeKind.FunnelsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: eventConfig?.event ?? '$pageview',
                properties: eventConfig?.properties ?? [],
            },
            baseProps,
        ],
        funnelsFilter: {
            funnelVizType: FunnelVizType.Steps,
        },
        filterTestAccounts: experiment.exposure_criteria?.filterTestAccounts === true,
        dateRange: {
            date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
            explicitDate: true,
        },
        interval: 'day',
    } as FunnelsQuery
}

export interface RunningTimeCalculatorLogicProps {
    experimentId?: Experiment['id']
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
    connect(({ experimentId }: RunningTimeCalculatorLogicProps) => ({
        values: [experimentLogic({ experimentId }), ['experiment']],
    })),
    actions({
        setMetricIndex: (value: number) => ({ value }),
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
        _metricIndex: [
            null as number | null,
            {
                setMetricIndex: (_, { value }) => value,
            },
        ],
        _conversionRateInputType: [
            ConversionRateInputType.AUTOMATIC as string,
            { setConversionRateInputType: (_, { value }) => value },
        ],
        _manualConversionRate: [2 as number, { setManualConversionRate: (_, { value }) => value }],
        _minimumDetectableEffect: [null as number | null, { setMinimumDetectableEffect: (_, { value }) => value }],
    }),
    loaders(({ values }) => ({
        metricResult: {
            loadMetricResult: async () => {
                if (values.metricIndex === null) {
                    return null
                }

                const metric = values.metric as ExperimentMetric

                if (!metric) {
                    return null
                }

                const query =
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.source.math === ExperimentMetricMathType.TotalCount
                        ? getTotalCountQuery(
                              metric,
                              values.experiment,
                              values.exposureEstimateConfig?.eventFilter ?? null
                          )
                        : metric.metric_type === ExperimentMetricType.MEAN &&
                          metric.source.math === ExperimentMetricMathType.Sum
                        ? getSumQuery(metric, values.experiment, values.exposureEstimateConfig?.eventFilter ?? null)
                        : getFunnelQuery(metric, values.exposureEstimateConfig?.eventFilter ?? null, values.experiment)

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
    listeners(({ actions, values }) => ({
        setMetricIndex: () => {
            // When metric index changes, update exposure estimate config with the new metric
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
    selectors({
        defaultMetricIndex: [
            (s) => [s.experiment, s.exposureEstimateConfig],
            (experiment: Experiment, exposureEstimateConfig: ExposureEstimateConfig | null): number | null => {
                if (!experiment?.metrics || !exposureEstimateConfig?.metric) {
                    return null
                }

                // First check regular metrics
                const metricIndex = experiment.metrics.findIndex((m) => equal(m, exposureEstimateConfig.metric))
                if (metricIndex >= 0) {
                    return metricIndex
                }

                // If not found, check shared metrics
                const primarySharedMetrics = experiment.saved_metrics.filter((m) => m.metadata.type === 'primary')
                const sharedMetricIndex = primarySharedMetrics.findIndex((m) =>
                    equal(m.query, exposureEstimateConfig.metric)
                )

                return sharedMetricIndex >= 0 ? experiment.metrics.length + sharedMetricIndex : null
            },
        ],
        metricIndex: [
            (s) => [s._metricIndex, s.defaultMetricIndex],
            (metricIndex: number | null, defaultMetricIndex: number | null): number | null => {
                // If metricIndex was manually set, use that
                // Otherwise use the default from exposureEstimateConfig if available
                return metricIndex ?? defaultMetricIndex
            },
        ],
        exposureEstimateConfig: [
            (s) => [s._exposureEstimateConfig, s.experiment],
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
                if (experiment.parameters.exposure_estimate_config) {
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
            (s) => [s._minimumDetectableEffect, s.experiment],
            (minimumDetectableEffect: number | null, experiment: Experiment) =>
                minimumDetectableEffect ?? experiment?.parameters?.minimum_detectable_effect ?? DEFAULT_MDE,
        ],
        metric: [
            (s) => [s.metricIndex, s.experiment],
            (metricIndex: number | null, experiment: Experiment): ExperimentMetric | null => {
                if (metricIndex === null) {
                    return null
                }

                // Check if the index is within the regular metrics array
                if (metricIndex < experiment.metrics.length) {
                    return experiment.metrics[metricIndex] as ExperimentMetric
                }

                // If not, check shared metrics with primary type
                const sharedMetricIndex = metricIndex - experiment.metrics.length
                const sharedMetric = experiment.saved_metrics.filter((m) => m.metadata.type === 'primary')[
                    sharedMetricIndex
                ]

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
            (metric: ExperimentMetric, averageEventsPerUser: number, averagePropertyValuePerUser: number) => {
                if (!metric) {
                    return null
                }

                if (
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.source.math === ExperimentMetricMathType.TotalCount
                ) {
                    return VARIANCE_SCALING_FACTOR_TOTAL_COUNT * averageEventsPerUser
                } else if (
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.source.math === ExperimentMetricMathType.Sum
                ) {
                    return VARIANCE_SCALING_FACTOR_SUM * averagePropertyValuePerUser ** 2
                }
                return null
            },
        ],
        standardDeviation: [(s) => [s.variance], (variance: number) => (variance ? Math.sqrt(variance) : null)],
        numberOfVariants: [
            (s) => [s.experiment],
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
            ): number | null => {
                if (!metric) {
                    return null
                }

                const minimumDetectableEffectDecimal = minimumDetectableEffect / 100

                let d // Represents the absolute effect size (difference we want to detect)
                let sampleSizeFormula // The correct sample size formula for each metric type

                if (
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.source.math === ExperimentMetricMathType.TotalCount
                ) {
                    /*
                        Count Per User Metric:
                        - "mean" is the average number of events per user (e.g., clicks per user).
                        - MDE is applied as a percentage of this mean to compute `d`.

                        Formula:
                        d = MDE * averageEventsPerUser
                    */
                    d = minimumDetectableEffectDecimal * averageEventsPerUser

                    /*
                        Sample size formula:

                        N = (16 * variance) / d^2

                        Where:
                        - `16` comes from statistical power analysis:
                            - Based on a 95% confidence level (Z_alpha/2 = 1.96) and 80% power (Z_beta = 0.84),
                              the combined squared Z-scores yield approximately 16.
                        - `variance` is the estimated variance of the event count per user.
                        - `d` is the absolute effect size (MDE * mean).
                    */
                    sampleSizeFormula = (16 * variance) / d ** 2
                } else if (
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.source.math === ExperimentMetricMathType.Sum
                ) {
                    /*
                        Continuous property metric:
                        - "mean" is the average value of the measured property per user (e.g., revenue per user).
                        - MDE is applied as a percentage of this mean to compute `d`.

                        Formula:
                        d = MDE * averagePropertyValuePerUser
                    */
                    d = minimumDetectableEffectDecimal * averagePropertyValuePerUser

                    /*
                        Sample Size Formula for Continuous metrics:

                        N = (16 * variance) / d^2

                        Where:
                        - `variance` is the estimated variance of the continuous property.
                        - The formula is identical to the Count metric case.
                    */
                    sampleSizeFormula = (16 * variance) / d ** 2
                } else if (metric.metric_type === ExperimentMetricType.FUNNEL) {
                    const manualConversionRateDecimal = manualConversionRate / 100
                    const conversionRate =
                        conversionRateInputType === ConversionRateInputType.MANUAL
                            ? manualConversionRateDecimal
                            : automaticConversionRateDecimal

                    /*
                        Binomial metric (conversion rate):
                        - Here, "mean" does not exist in the same way as for count/continuous metrics.
                        - Instead, we use `p`, the baseline conversion rate (historical probability of success).
                        - MDE is applied as an absolute percentage change to `p`.

                        Formula:
                        d = MDE * conversionRate
                    */
                    d = minimumDetectableEffectDecimal * conversionRate

                    /*
                        Sample size formula:

                        N = (16 * p * (1 - p)) / d^2

                        Where:
                        - `p` is the historical conversion rate (baseline success probability).
                        - `d` is the absolute MDE (e.g., detecting a 5% increase means `d = 0.05`).
                        - The variance is inherent in `p(1 - p)`, which represents binomial variance.
                    */
                    if (conversionRate !== null) {
                        sampleSizeFormula = (16 * conversionRate * (1 - conversionRate)) / d ** 2
                    } else {
                        return null
                    }
                }

                if (!d || !sampleSizeFormula) {
                    return null
                }

                return sampleSizeFormula * numberOfVariants
            },
        ],
        recommendedRunningTime: [
            (s) => [s.recommendedSampleSize, s.uniqueUsers],
            (recommendedSampleSize: number, uniqueUsers: number): number => {
                return recommendedSampleSize / (uniqueUsers / TIMEFRAME_HISTORICAL_DATA_DAYS)
            },
        ],
    }),
])
