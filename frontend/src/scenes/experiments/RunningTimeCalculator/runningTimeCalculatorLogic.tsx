import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { performQuery } from '~/queries/query'
import { ExperimentMetric, ExperimentMetricType, NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { BaseMathType, CountPerActorMathType, Experiment, PropertyMathType } from '~/types'

import type { runningTimeCalculatorLogicType } from './runningTimeCalculatorLogicType'

export const TIMEFRAME_HISTORICAL_DATA_DAYS = 14
export const VARIANCE_SCALING_FACTOR_COUNT = 2
export const VARIANCE_SCALING_FACTOR_CONTINUOUS = 0.25

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

                const series = []

                const kindField =
                    metric.metric_config.kind === NodeKind.ExperimentEventMetricConfig
                        ? NodeKind.EventsNode
                        : metric.metric_config.kind === NodeKind.ExperimentActionMetricConfig
                        ? NodeKind.ActionsNode
                        : NodeKind.DataWarehouseNode

                const eventField =
                    metric.metric_config.kind === NodeKind.ExperimentEventMetricConfig
                        ? metric.metric_config.event
                        : metric.metric_config.kind === NodeKind.ExperimentActionMetricConfig
                        ? metric.metric_config.action
                        : metric.metric_config.table_name

                series.push({
                    kind: kindField,
                    event: eventField,
                    math: BaseMathType.UniqueUsers,
                })

                if (metric.metric_type === ExperimentMetricType.COUNT) {
                    series.push({
                        kind: kindField,
                        event: eventField,
                        math: CountPerActorMathType.Average,
                    })
                } else if (metric.metric_type === ExperimentMetricType.CONTINUOUS) {
                    series.push({
                        kind: kindField,
                        event: eventField,
                        math: PropertyMathType.Sum,
                        math_property: metric.metric_config.math_property,
                        math_property_type: TaxonomicFilterGroupType.NumericalEventProperties,
                    })
                }

                const query = {
                    kind: NodeKind.TrendsQuery,
                    series,
                    trendsFilter: {},
                    filterTestAccounts: values.experiment.exposure_criteria?.filterTestAccounts === true,
                    dateRange: {
                        date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                        date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                        explicitDate: true,
                    },
                }

                const result = (await performQuery(query)) as Partial<TrendsQueryResponse>

                return {
                    uniqueUsers: result?.results?.[0]?.count ?? null,
                    ...(metric.metric_type === ExperimentMetricType.COUNT
                        ? { averageEventsPerUser: result?.results?.[1]?.count ?? null }
                        : {}),
                    ...(metric.metric_type === ExperimentMetricType.CONTINUOUS
                        ? { averagePropertyValuePerUser: result?.results?.[1]?.count ?? null }
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
        variance: [
            (s) => [s.metric, s.averageEventsPerUser, s.averagePropertyValuePerUser],
            (metric: ExperimentMetric, averageEventsPerUser: number, averagePropertyValuePerUser: number) => {
                if (!metric) {
                    return null
                }

                if (metric.metric_type === ExperimentMetricType.COUNT) {
                    return VARIANCE_SCALING_FACTOR_COUNT * averageEventsPerUser
                } else if (metric.metric_type === ExperimentMetricType.CONTINUOUS) {
                    return VARIANCE_SCALING_FACTOR_CONTINUOUS * averagePropertyValuePerUser ** 2
                }
                return null
            },
        ],
        recommendedSampleSize: [
            (s) => [s.metric, s.minimumDetectableEffect, s.variance, s.averagePropertyValuePerUser],
            (
                metric: ExperimentMetric,
                minimumDetectableEffect: number,
                variance: number,
                averagePropertyValuePerUser: number
            ): number | null => {
                const numberOfVariants = 2
                const standardDeviation = Math.sqrt(variance)

                if (metric.metric_type === ExperimentMetricType.COUNT) {
                    return (
                        ((16 * variance) / ((minimumDetectableEffect / 100) * standardDeviation) ** 2) *
                        numberOfVariants
                    )
                } else if (metric.metric_type === ExperimentMetricType.CONTINUOUS) {
                    return (
                        ((16 * variance) / ((minimumDetectableEffect / 100) * averagePropertyValuePerUser) ** 2) *
                        numberOfVariants
                    )
                }

                return null
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
