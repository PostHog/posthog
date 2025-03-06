import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { performQuery } from '~/queries/query'
import {
    ExperimentMetric,
    ExperimentMetricType,
    FunnelsQuery,
    NodeKind,
    TrendsQuery,
    TrendsQueryResponse,
} from '~/queries/schema/schema-general'
import {
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

const getKindField = (metric: ExperimentMetric): NodeKind => {
    return metric.metric_config.kind === NodeKind.ExperimentEventMetricConfig
        ? NodeKind.EventsNode
        : metric.metric_config.kind === NodeKind.ExperimentActionMetricConfig
        ? NodeKind.ActionsNode
        : NodeKind.DataWarehouseNode
}

const getEventField = (metric: ExperimentMetric): string | number => {
    return metric.metric_config.kind === NodeKind.ExperimentEventMetricConfig
        ? metric.metric_config.event
        : metric.metric_config.kind === NodeKind.ExperimentActionMetricConfig
        ? metric.metric_config.action
        : metric.metric_config.table_name
}

const getTotalCountQuery = (metric: ExperimentMetric, experiment: Experiment): TrendsQuery => {
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: getKindField(metric),
                event: getEventField(metric),
                math: BaseMathType.UniqueUsers,
            },
            {
                kind: getKindField(metric),
                event: getEventField(metric),
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

const getSumQuery = (metric: ExperimentMetric, experiment: Experiment): TrendsQuery => {
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: getKindField(metric),
                event: getEventField(metric),
                math: BaseMathType.UniqueUsers,
            },
            {
                kind: getKindField(metric),
                event: getEventField(metric),
                math: PropertyMathType.Sum,
                math_property: metric.metric_config.math_property,
                math_property_type: TaxonomicFilterGroupType.NumericalEventProperties,
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

const getFunnelQuery = (metric: ExperimentMetric, experiment: Experiment): FunnelsQuery => {
    return {
        kind: NodeKind.FunnelsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$feature_flag_called',
            },
            {
                kind: getKindField(metric),
                event: getEventField(metric),
            },
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

export const runningTimeCalculatorLogic = kea<runningTimeCalculatorLogicType>([
    path(['scenes', 'experiments', 'RunningTimeCalculator', 'runningTimeCalculatorLogic']),
    connect(({ experimentId }: RunningTimeCalculatorLogicProps) => ({
        values: [experimentLogic({ experimentId }), ['experiment']],
    })),
    actions({
        setMinimumDetectableEffect: (value: number) => ({ value }),
        setMetricIndex: (value: number) => ({ value }),
        setMetricResult: (value: {
            uniqueUsers: number
            averageEventsPerUser?: number
            averagePropertyValuePerUser?: number
            conversionRate?: number
        }) => ({ value }),
    }),
    reducers({
        metricIndex: [
            null as number | null,
            {
                setMetricIndex: (_, { value }) => value,
            },
        ],
        eventOrAction: ['click' as string, { setEventOrAction: (_, { value }) => value }],
        minimumDetectableEffect: [
            5 as number,
            {
                setMinimumDetectableEffect: (_, { value }) => value,
            },
        ],
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
                    metric.metric_config.math === ExperimentMetricMathType.TotalCount
                        ? getTotalCountQuery(metric, values.experiment)
                        : metric.metric_type === ExperimentMetricType.MEAN &&
                          metric.metric_config.math === ExperimentMetricMathType.Sum
                        ? getSumQuery(metric, values.experiment)
                        : getFunnelQuery(metric, values.experiment)

                const result = (await performQuery(query)) as Partial<TrendsQueryResponse>

                return {
                    uniqueUsers: result?.results?.[0]?.count ?? null,
                    ...(metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.metric_config.math === ExperimentMetricMathType.TotalCount
                        ? { averageEventsPerUser: result?.results?.[1]?.count ?? null }
                        : {}),
                    ...(metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.metric_config.math === ExperimentMetricMathType.Sum
                        ? { averagePropertyValuePerUser: result?.results?.[1]?.count ?? null }
                        : {}),
                    ...(metric.metric_type === ExperimentMetricType.FUNNEL
                        ? { conversionRate: result?.results?.[1]?.count / result?.results?.[0]?.count || null }
                        : {}),
                }
            },
            // For testing purposes, we want to be able set the metric result directly
            setMetricResult: ({ value }) => value,
        },
    })),
    listeners(({ actions }) => ({
        setMetricIndex: () => {
            actions.loadMetricResult()
        },
    })),
    selectors({
        metric: [
            (s) => [s.metricIndex, s.experiment],
            (metricIndex: number, experiment: Experiment) => experiment.metrics[metricIndex],
        ],
        uniqueUsers: [
            (s) => [s.metricResult],
            (metricResult: { uniqueUsers: number }) => metricResult?.uniqueUsers ?? null,
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
        conversionRate: [
            (s) => [s.metricResult],
            (metricResult: { conversionRate: number }) => metricResult?.conversionRate ?? null,
        ],
        variance: [
            (s) => [s.metric, s.averageEventsPerUser, s.averagePropertyValuePerUser],
            (metric: ExperimentMetric, averageEventsPerUser: number, averagePropertyValuePerUser: number) => {
                if (!metric) {
                    return null
                }

                if (
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.metric_config.math === ExperimentMetricMathType.TotalCount
                ) {
                    return VARIANCE_SCALING_FACTOR_TOTAL_COUNT * averageEventsPerUser
                } else if (
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.metric_config.math === ExperimentMetricMathType.Sum
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
                s.conversionRate,
                s.numberOfVariants,
            ],
            (
                metric: ExperimentMetric,
                minimumDetectableEffect: number,
                variance: number,
                averageEventsPerUser: number,
                averagePropertyValuePerUser: number,
                conversionRate: number,
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
                    metric.metric_config.math === ExperimentMetricMathType.TotalCount
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
                    metric.metric_config.math === ExperimentMetricMathType.Sum
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
                    /*
                        Binomial metric (conversion rate):
                        - Here, "mean" does not exist in the same way as for count/continuous metrics.
                        - Instead, we use `p`, the baseline conversion rate (historical probability of success).
                        - MDE is applied as an absolute percentage change to `p`.
        
                        Formula:
                        d = MDE (absolute percentage point change)
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
