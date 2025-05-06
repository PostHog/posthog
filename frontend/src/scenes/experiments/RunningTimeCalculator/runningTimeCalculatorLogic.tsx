// import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DEFAULT_MDE, experimentLogic } from 'scenes/experiments/experimentLogic'

import { performQuery } from '~/queries/query'
import {
    ExperimentMetric,
    ExperimentMetricType,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    TrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, Experiment, ExperimentMetricMathType } from '~/types'

import { getFunnelQuery, getSumQuery, getTotalCountQuery } from './metricQueryUtils'
import type { runningTimeCalculatorLogicType } from './runningTimeCalculatorLogicType'

export const TIMEFRAME_HISTORICAL_DATA_DAYS = 14
export const VARIANCE_SCALING_FACTOR_TOTAL_COUNT = 2
export const VARIANCE_SCALING_FACTOR_SUM = 0.25

export enum ConversionRateInputType {
    MANUAL = 'manual',
    AUTOMATIC = 'automatic',
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
    /**
     * This is the metric that we're estimating the exposure for.
     */
    metric: ExperimentMetric | null
    /**
     * This is the type of conversion rate input that we're using.
     */
    conversionRateInputType: ConversionRateInputType
    /**
     * This is the manual conversion rate that we're using.
     */
    manualConversionRate: number | null
    /**
     * This is the number of unique users that we're estimating the exposure for.
     */
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
        setExposureEstimateConfig: (value: ExposureEstimateConfig) => ({ value }),
        setMetricResult: (value: {
            uniqueUsers: number
            averageEventsPerUser?: number
            averagePropertyValuePerUser?: number
            automaticConversionRateDecimal?: number
        }) => ({ value }),
        setConversionRateInputType: (value: string) => ({ value }),
        setManualConversionRate: (value: number) => ({ value }),
        setMinimumDetectableEffect: (value: number) => ({ value }),
    }),
    reducers({
        _exposureEstimateConfig: [
            null as ExposureEstimateConfig | null,
            { setExposureEstimateConfig: (_, { value }) => value },
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
                return null
            },
        },
        /**
         * This loader will create the following actions:
         * - loadExposureEstimate
         * - loadExposureEstimateSucess
         * - loadExposureEstimateFailure
         *
         * and these reducers:
         * - exposureEstimate
         * - exposureEstimateLoading
         */
        exposureEstimate: {
            loadExposureEstimate: async (metric: ExperimentMetric) => {
                if (!metric) {
                    return null
                }

                const query =
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.source.math === ExperimentMetricMathType.TotalCount
                        ? getTotalCountQuery(metric, values.experiment)
                        : metric.metric_type === ExperimentMetricType.MEAN &&
                          metric.source.math === ExperimentMetricMathType.Sum
                        ? getSumQuery(metric, values.experiment)
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
            setMetricResult: ({ value }) => value,
        },
    })),
    listeners(({ actions }) => ({
        loadExposureEstimateSuccess: ({ exposureEstimate }) => {
            actions.setMetricResult({
                uniqueUsers: exposureEstimate?.uniqueUsers ?? null,
                ...(exposureEstimate?.automaticConversionRateDecimal
                    ? { automaticConversionRateDecimal: exposureEstimate.automaticConversionRateDecimal }
                    : {}),
            })
        },
    })),
    selectors({
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
            (s) => [s.exposureEstimateConfig],
            (exposureEstimateConfig: ExposureEstimateConfig | null) => exposureEstimateConfig?.metric,
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
