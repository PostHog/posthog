import { actions, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { performQuery } from '~/queries/query'
import type {
    AnyEntityNode,
    ExperimentEventExposureConfig,
    ExperimentMetric,
    FunnelsQuery,
    InsightQueryNode,
    InsightVizNode,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind, ResultCustomizationBy } from '~/queries/schema/schema-general'
import type { Experiment, FunnelStep, TrendResult } from '~/types'
import {
    BreakdownAttributionType,
    ChartDisplayType,
    FunnelConversionWindowTimeUnit,
    FunnelStepReference,
    FunnelVizType,
    PropertyFilterType,
    PropertyOperator,
    StepOrderValue,
} from '~/types'

import type { experimentResultBreakdownLogicType } from './experimentResultBreakdownLogicType'
import { getExperimentDateRange, getInsightWithExposure } from './metricQueryUtils'

export type ExperimentResultBreakdownLogicProps = {
    experiment: Experiment
    metric: ExperimentMetric
}

export type BreakDownResults = {
    query: InsightVizNode<InsightQueryNode>
    results: FunnelStep[] | FunnelStep[][] | TrendResult[]
}

/**
 * This logic only works with modern engines, like bayesian and frequentist.
 * Legacy Funnels and Trends engine are resolved backend side.
 */
export const experimentResultBreakdownLogic = kea<experimentResultBreakdownLogicType>([
    props({
        experiment: {} as Experiment,
        metric: {} as ExperimentMetric,
    } as ExperimentResultBreakdownLogicProps),

    key(
        ({ experiment, metric }: ExperimentResultBreakdownLogicProps) =>
            `${experiment.id}-${metric.kind}-${metric.name}`
    ),

    path((key) => ['scenes', 'experiment', 'experimentResultBreakdownLogic', key]),

    actions({
        loadBreakdownResults: true,
    }),

    loaders(({ props }) => ({
        breakdownResults: [
            null as BreakDownResults | null,
            {
                loadBreakdownResults: async (): Promise<BreakDownResults> => {
                    try {
                        const { metric, experiment } = props
                        /**
                         * take the metric and the experiment and create a new Funnel or Trends query.
                         * we need the experiment for exposure configuration.
                         */
                        const query = getInsightWithExposure(
                            metric,
                            experiment.exposure_criteria?.exposure_config as ExperimentEventExposureConfig,
                            {
                                showTable: true,
                                showLastComputation: true,
                                showLastComputationRefresh: false,
                                featureFlagKey: experiment.feature_flag_key,
                                featureFlagVariants: experiment.parameters.feature_flag_variants,
                                queryOptions: {
                                    filterTestAccounts: !!experiment.exposure_criteria?.filterTestAccounts,
                                    dateRange: getExperimentDateRange(experiment),
                                    breakdownFilter: {
                                        breakdown: `$feature/${experiment.feature_flag_key}`,
                                        breakdown_type: 'event',
                                    },
                                    funnelsFilter: {
                                        layout: FunnelLayout.vertical,
                                        breakdownAttributionType: BreakdownAttributionType.FirstTouch,
                                        funnelOrderType: StepOrderValue.ORDERED,
                                        funnelStepReference: FunnelStepReference.total,
                                        funnelVizType: FunnelVizType.Steps,
                                        funnelWindowInterval: 14,
                                        funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                                    },
                                    trendsFilter: {
                                        aggregationAxisFormat: 'numeric',
                                        display: ChartDisplayType.ActionsLineGraphCumulative,
                                        resultCustomizationBy: ResultCustomizationBy.Value,
                                        yAxisScaleType: 'linear',
                                    },
                                },
                            }
                        )

                        /**
                         * perform the query
                         */
                        const response = (await performQuery(query)) as {
                            results: FunnelStep[] | FunnelStep[][] | TrendResult[]
                        }

                        if (!response?.results) {
                            throw new Error('No results returned from query')
                        }

                        let results = response.results as FunnelStep[] | FunnelStep[][] | TrendResult[]

                        /**
                         * we need to filter the results to remove any non-variant breakdown
                         */
                        const variants = experiment.parameters.feature_flag_variants.map(({ key }) => key)

                        if (query.source.kind === NodeKind.TrendsQuery) {
                            /**
                             * we filter from the series all the breakdowns that do not map
                             * to a feature flag variant
                             */
                            results = (results as TrendResult[]).filter(
                                (series) =>
                                    series.breakdown_value !== undefined &&
                                    variants.includes(series.breakdown_value as string)
                            )
                        }

                        return { query, results }
                    } catch (error) {
                        throw new Error(
                            error instanceof Error
                                ? `Failed to load experiment results: ${error.message}`
                                : 'Failed to load experiment results'
                        )
                    }
                },
            },
        ],
    })),

    afterMount(({ actions, props }) => {
        const { metric, experiment } = props

        // bail if no valid props
        if (!experiment || !metric) {
            return
        }

        // bail if unsupported metric type
        if (metric.kind !== NodeKind.ExperimentMetric) {
            return
        }

        actions.loadBreakdownResults()
    }),
])
