import { actions, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { performQuery } from '~/queries/query'
import type { AnyEntityNode, ExperimentMetric, FunnelsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment, FunnelStep, TrendResult } from '~/types'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { experimentResultBreakdownLogicType } from './experimentResultBreakdownLogicType'

/**
 * takes the experiment's exposure criteria and feature flag settings to create a
 * EntityNode series that can be used on a Funnel or Trends query.
 */
const exposureCriteriaToEntityNode = (experiment: Experiment): AnyEntityNode[] => {
    const series: AnyEntityNode[] = []

    const exposureCriteria = experiment.exposure_criteria?.exposure_config
    if (exposureCriteria && exposureCriteria.event !== '$feature_flag_called') {
        series.push({
            kind: NodeKind.EventsNode,
            custom_name: exposureCriteria.event,
            event: exposureCriteria.event,
            properties: [
                ...(exposureCriteria.properties || []),
                {
                    key: `$feature/${experiment.feature_flag_key}`,
                    type: PropertyFilterType.Event,
                    value: experiment.parameters.feature_flag_variants.map(({ key }) => key),
                    operator: PropertyOperator.Exact,
                },
            ],
        })
    } else {
        series.push({
            kind: NodeKind.EventsNode,
            custom_name: '$feature_flag_called',
            event: '$feature_flag_called',
            properties: [
                {
                    key: '$feature_flag',
                    type: PropertyFilterType.Event,
                    value: experiment.feature_flag_key,
                    operator: PropertyOperator.Exact,
                },
            ],
        })
    }

    return series
}

/**
 * takes and experiment metric and an experiment (for the exposure criteria) and
 * returns a Funnel or Trends query to be used to make an insight query.
 */
const experimentMetricToInsightQuery = (
    metric: ExperimentMetric,
    experiment: Experiment
): FunnelsQuery | TrendsQuery => {
    /**
     * the first entity node of the query will be the exposure criteria
     */
    const exposureCriteriaSeries = exposureCriteriaToEntityNode(experiment)

    /**
     * for mean metrics, we take the single source element into the query
     */
    return {
        kind: metric.metric_type === ExperimentMetricType.FUNNEL ? NodeKind.FunnelsQuery : NodeKind.TrendsQuery,
        series:
            metric.metric_type === ExperimentMetricType.FUNNEL
                ? [...exposureCriteriaSeries, ...metric.series]
                : [metric.source as AnyEntityNode],
        filterTestAccounts: !!experiment.exposure_criteria?.filterTestAccounts,
        dateRange: {
            date_from:
                experiment.start_date ||
                dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: experiment.end_date,
            explicitDate: true,
        },
        breakdownFilter: {
            breakdown: `$feature/${experiment.feature_flag_key}`,
            breakdown_type: 'event',
        },

        ...(metric.metric_type === ExperimentMetricType.FUNNEL
            ? {
                  funnelsFilter: {
                      layout: FunnelLayout.vertical,
                      breakdownAttributionType: 'first_touch',
                      funnelOrderType: 'ordered',
                      funnelStepReference: 'total',
                      funnelVizType: 'steps',
                      funnelWindowInterval: 14,
                      funnelWindowIntervalUnit: 'day',
                  },
              }
            : {
                  trendsFilter: {
                      aggregationAxisFormat: 'numeric',
                      display: 'ActionsLineGraphCumulative',
                      resultCustomizationBy: 'value',
                      yAxisScaleType: 'linear',
                  },
              }),
    } as FunnelsQuery | TrendsQuery
}

export type ExperimentResultBreakdownLogicProps = {
    experiment: Experiment
    metric: ExperimentMetric
}

export type BreakDownResults = {
    query: FunnelsQuery | TrendsQuery
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
                        const query = experimentMetricToInsightQuery(metric, experiment)

                        /**
                         * perform the query
                         */
                        const response = await performQuery(query)

                        if (!response?.results) {
                            throw new Error('No results returned from query')
                        }

                        let results = response.results as FunnelStep[] | FunnelStep[][] | TrendResult[]

                        /**
                         * we need to filter the results to remove any non-variant breakdown
                         */
                        const variants = experiment.parameters.feature_flag_variants.map(({ key }) => key)

                        if (query.kind === NodeKind.TrendsQuery) {
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
