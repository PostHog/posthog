// import equal from 'fast-deep-equal'
import { actions, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

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

export type ExposureEstimateResult = {
    uniqueUsers: number | null
    averageEventsPerUser?: number | null
    averagePropertyValuePerUser?: number | null
    automaticConversionRateDecimal?: number | null
} | null

export const runningTimeCalculatorLogic = kea<runningTimeCalculatorLogicType>([
    path(['scenes', 'experiments', 'RunningTimeCalculator', 'runningTimeCalculatorLogic']),

    connect(({ experimentId }: RunningTimeCalculatorLogicProps) => ({
        values: [experimentLogic({ experimentId }), ['experiment']],
    })),

    actions({
        /**
         * We create this action to be able to call the loader with the correct parameters.
         */
        loadExposureEstimate: (
            experiment: Experiment,
            exposureEstimateConfig: ExposureEstimateConfig,
            metric: ExperimentMetric
        ) => ({ experiment, exposureEstimateConfig, metric }),
    }),

    loaders(() => ({
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
            loadExposureEstimate: async ({ experiment, exposureEstimateConfig, metric }) => {
                if (!metric) {
                    return null
                }

                const query =
                    metric.metric_type === ExperimentMetricType.MEAN &&
                    metric.source.math === ExperimentMetricMathType.TotalCount
                        ? getTotalCountQuery(metric, experiment)
                        : metric.metric_type === ExperimentMetricType.MEAN &&
                          metric.source.math === ExperimentMetricMathType.Sum
                        ? getSumQuery(metric, experiment)
                        : getFunnelQuery(metric, exposureEstimateConfig.eventFilter ?? null, experiment)

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

                return null
            },
        },
    })),
])
