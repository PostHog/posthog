import { actions, afterMount, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { FunnelLayout } from 'lib/constants'

import { performQuery } from '~/queries/query'
import type {
    ExperimentEventExposureConfig,
    ExperimentMetric,
    FunnelsQuery,
    InsightVizNode,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { NodeKind, ResultCustomizationBy } from '~/queries/schema/schema-general'
import {
    addExposureToMetric,
    compose,
    getExperimentDateRange,
    getExposureConfigEventsNode,
    getInsight,
    getQuery,
} from '~/scenes/experiments/metricQueryUtils'
import type { Experiment, FunnelStep, TrendResult } from '~/types'
import {
    BreakdownAttributionType,
    ChartDisplayType,
    FunnelConversionWindowTimeUnit,
    FunnelStepReference,
    FunnelVizType,
    StepOrderValue,
} from '~/types'

import type { resultsBreakdownLogicType } from './resultsBreakdownLogicType'

export type ResultBreakdownLogicProps = {
    experiment: Experiment
    metric?: ExperimentMetric
}

/**
 * This logic only works with the new query runner.
 * Legacy Funnels and Trends engine are resolved backend side.
 */
export const resultsBreakdownLogic = kea<resultsBreakdownLogicType>([
    props({
        experiment: {} as Experiment,
        metric: {} as ExperimentMetric,
    } as ResultBreakdownLogicProps),

    path((key) => ['scenes', 'experiment', 'experimentResultBreakdownLogic', key]),

    actions({
        loadBreakdownResults: true,
    }),

    selectors({
        query: [
            () => [(_, props) => props],
            ({ experiment, metric }: ResultBreakdownLogicProps) => {
                if (!metric) {
                    return null
                }

                /**
                 * we create the exposure node. For this case, we need
                 * need to use the experiment's exposure config
                 */
                const exposureEventNode = getExposureConfigEventsNode(
                    experiment.exposure_criteria?.exposure_config as ExperimentEventExposureConfig,
                    {
                        featureFlagKey: experiment.feature_flag_key,
                        featureFlagVariants: experiment.parameters.feature_flag_variants,
                    }
                )

                /**
                 * we create the query builder with all the options.
                 */
                const queryBuilder = compose<
                    ExperimentMetric,
                    ExperimentMetric,
                    FunnelsQuery | TrendsQuery | undefined,
                    InsightVizNode | undefined
                >(
                    addExposureToMetric(exposureEventNode),
                    getQuery({
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
                    }),
                    getInsight({
                        showTable: true,
                        showLastComputation: true,
                        showLastComputationRefresh: false,
                    })
                )

                /**
                 * take the metric and the experiment and create a new Funnel or Trends query.
                 * we need the experiment for exposure configuration.
                 */
                return queryBuilder(metric) || null
            },
        ],
    }),

    loaders(({ props, values }) => ({
        breakdownResults: [
            null as FunnelStep[] | FunnelStep[][] | TrendResult[] | null,
            {
                loadBreakdownResults: async (): Promise<FunnelStep[] | FunnelStep[][] | TrendResult[]> => {
                    try {
                        const { experiment } = props
                        const query = values.query

                        if (!query) {
                            throw new Error('No query returned from queryBuilder')
                        }

                        /**
                         * perform the query
                         */
                        const response = (await performQuery(query)) as {
                            results: FunnelStep[] | FunnelStep[][] | TrendResult[]
                        }

                        if (!response?.results) {
                            throw new Error('No results returned from query')
                        }

                        let results = response.results

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

                        return results
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
