import { actions, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import { FunnelLayout } from 'lib/constants'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { performQuery } from '~/queries/query'
import type { AnyEntityNode, ExperimentMetric, FunnelsQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

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
        })
    } else {
        series.push({
            kind: NodeKind.EventsNode,
            custom_name: 'exposures',
            event: '$feature_flag_called',
        })
        // series.push({
        //     id: '$feature_flag_called',
        //     name: '$feature_flag_called',
        //     type: 'events',
        //     properties: [
        //         {
        //             key: '$feature_flag_response',
        //             type: PropertyFilterType.Event,
        //             value: [variantKey],
        //             operator: PropertyOperator.Exact,
        //         },
        //         {
        //             key: '$feature_flag',
        //             type: PropertyFilterType.Event,
        //             value: experiment.feature_flag_key,
        //             operator: PropertyOperator.Exact,
        //         },
        //     ],
        // })
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
            // date_from: '2025-02-28T21:45:00+00:00',
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
            funnelWindowInterval: 14, //<- need to fix this
            funnelWindowIntervalUnit: 'day',
        },
        breakdownFilter: {
            breakdown: `$feature/${experiment.feature_flag_key}`,
            breakdown_type: 'event',
        },
    } as FunnelsQuery
}

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
                loadBreakdownResults: async () => {
                    const query = metricToQuery(props.metric, props.experiment)

                    const response = await performQuery(query)

                    /**
                     * filter results to only include valid variants in the first step
                     */
                    const results = response.results
                    // for now, just remove the first item. We'll make it better tomorrow...
                    results.shift()

                    return { query, insight: response.results }
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
