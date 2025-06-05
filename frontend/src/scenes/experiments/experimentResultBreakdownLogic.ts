import { actions, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { performQuery } from '~/queries/query'
import type {
    AnyEntityNode,
    ExperimentMetric,
    FunnelsQuery,
    FunnelStepsResults,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { experimentResultBreakdownLogicType } from './experimentResultBreakdownLogicType'

type ExperimentResultBreakdownLogicProps = {
    experiment: Experiment
    metric: ExperimentMetric
}

const metricToQuery = (metric: ExperimentMetric, experiment: Experiment): FunnelsQuery | TrendsQuery => {
    const series: AnyEntityNode[] = []

    /**
     * the first item of the thing will be the exposure criteria
     */
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

    /**
     * for funnel metrics, we need to add each element in the series as a filter
     */
    if (metric.metric_type === ExperimentMetricType.FUNNEL) {
        metric.series.forEach((s) => {
            if (s.kind === NodeKind.EventsNode) {
                series.push({
                    kind: NodeKind.EventsNode,
                    custom_name: s.event ?? undefined,
                    event: s.event,
                })
            }
        })
    }

    return {
        kind: 'FunnelsQuery',
        series,
        filterTestAccounts: !!experiment.exposure_criteria?.filterTestAccounts,
        dateRange: {
            date_from:
                experiment.start_date ||
                dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
            date_to: experiment.end_date,
            explicitDate: true,
        },
        funnelsFilter: {
            layout: FunnelLayout.vertical,
            breakdownAttributionType: 'first_touch',
            funnelOrderType: 'ordered',
            funnelStepReference: 'total',
            funnelVizType: 'steps',
            funnelWindowInterval: 14,
            funnelWindowIntervalUnit: 'day',
        },
        breakdownFilter: {
            breakdown: `$feature/${experiment.feature_flag_key}`,
            breakdown_type: 'event',
        },
    } as FunnelsQuery
}

/**
 * This logic only works with modern engines, like bayesian and frequentist.
 * Legacy Funnels and Trends engine are resolved backend side.
 */
export const experimentResultBreakdownLogic = kea<experimentResultBreakdownLogicType>([
    props({} as ExperimentResultBreakdownLogicProps),

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
            null as any,
            {
                loadBreakdownResults: async (): Promise<{
                    query: FunnelsQuery | TrendsQuery
                    results: FunnelStepsResults
                }> => {
                    const { metric, experiment } = props
                    /**
                     * take the metric and the experiment and create a new Funnel or Trends query.
                     * we need the experiment for exposure configuration.
                     */
                    const query = metricToQuery(metric, experiment)

                    /**
                     * perform the query
                     */
                    const response = await performQuery(query)

                    /**
                     * we need to filter the results
                     */
                    const results = response.results as FunnelStepsResults

                    return { query, results }
                },
            },
        ],
    })),

    afterMount(({ actions, props }) => {
        const { metric } = props

        if (metric.kind !== NodeKind.ExperimentMetric) {
            return
        }

        actions.loadBreakdownResults()
    }),
])
