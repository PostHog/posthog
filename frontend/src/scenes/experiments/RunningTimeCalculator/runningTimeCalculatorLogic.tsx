import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { performQuery } from '~/queries/query'
import { ExperimentMetric, NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { BaseMathType, CountPerActorMathType, Experiment } from '~/types'

import type { runningTimeCalculatorLogicType } from './runningTimeCalculatorLogicType'

export const TIMEFRAME_HISTORICAL_DATA_DAYS = 14
export const VARIANCE_SCALING_FACTOR = 2

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
        setMetricResult: (value: { uniqueUsers: number; averageEventsPerUser: number }) => ({ value }),
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

                const metric = values.experiment.metrics[values.metricIndex] as ExperimentMetric

                if (!metric) {
                    return null
                }

                let series

                if (metric.metric_config.kind === NodeKind.ExperimentEventMetricConfig) {
                    series = [
                        {
                            kind: NodeKind.EventsNode,
                            event: metric.metric_config.event,
                            math: BaseMathType.UniqueUsers,
                        },
                        {
                            kind: NodeKind.EventsNode,
                            event: metric.metric_config.event,
                            math: CountPerActorMathType.Average,
                        },
                    ]
                } else if (metric.metric_config.kind === NodeKind.ExperimentActionMetricConfig) {
                    series = [
                        {
                            kind: NodeKind.ActionsNode,
                            action: metric.metric_config.action,
                            math: BaseMathType.UniqueUsers,
                        },
                        {
                            kind: NodeKind.ActionsNode,
                            action: metric.metric_config.action,
                            math: CountPerActorMathType.Average,
                        },
                    ]
                } else if (metric.metric_config.kind === NodeKind.ExperimentDataWarehouseMetricConfig) {
                    series = [
                        {
                            kind: NodeKind.DataWarehouseNode,
                            table_name: metric.metric_config.table_name,
                            math: BaseMathType.UniqueUsers,
                        },
                        {
                            kind: NodeKind.DataWarehouseNode,
                            table_name: metric.metric_config.table_name,
                            math: CountPerActorMathType.Average,
                        },
                    ]
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
                    averageEventsPerUser: result?.results?.[1]?.count ?? null,
                }
            },
            // For testing purposes, we want to set the metric result directly
            setMetricResult: ({ value }) => value,
        },
    })),
    listeners(({ actions }) => ({
        setMetricIndex: () => {
            actions.loadMetricResult()
        },
    })),
    selectors({
        uniqueUsers: [
            (s) => [s.metricResult],
            (metricResult: { uniqueUsers: number }) => metricResult?.uniqueUsers ?? null,
        ],
        averageEventsPerUser: [
            (s) => [s.metricResult],
            (metricResult: { averageEventsPerUser: number }) => metricResult?.averageEventsPerUser ?? null,
        ],
        variance: [
            (s) => [s.averageEventsPerUser],
            (averageEventsPerUser: number) => {
                return averageEventsPerUser * VARIANCE_SCALING_FACTOR
            },
        ],
        recommendedSampleSize: [
            (s) => [s.minimumDetectableEffect, s.variance],
            (minimumDetectableEffect: number, variance: number): number => {
                const numberOfVariants = 2
                const standardDeviation = Math.sqrt(variance)

                return ((16 * variance) / ((minimumDetectableEffect / 100) * standardDeviation) ** 2) * numberOfVariants
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
