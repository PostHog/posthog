import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { InsightViz } from '~/queries/nodes/InsightViz/InsightViz'
import {
    CachedExperimentTrendsQueryResponse,
    InsightQueryNode,
    InsightVizNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightType, PropertyFilterType, PropertyOperator } from '~/types'

import { experimentLogic } from '../experimentLogic'

export function CumulativeExposuresChart(): JSX.Element {
    const { experiment, metricResults, getMetricType } = useValues(experimentLogic)

    const metricIdx = 0
    const metricType = getMetricType(experiment.metrics[metricIdx])
    const result = metricResults?.[metricIdx]
    const variants = experiment.parameters?.feature_flag_variants?.map((variant) => variant.key) || []
    if (experiment.holdout) {
        variants.push(`holdout-${experiment.holdout.id}`)
    }

    let query: InsightVizNode<InsightQueryNode>

    if (metricType === InsightType.TRENDS) {
        query = {
            kind: NodeKind.InsightVizNode,
            source: (result as CachedExperimentTrendsQueryResponse)?.exposure_query || {
                kind: NodeKind.TrendsQuery,
                series: [],
                interval: 'day',
            },
        }
    } else {
        query = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                dateRange: {
                    date_from: experiment.start_date,
                    date_to: experiment.end_date,
                },
                interval: 'day',
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraphCumulative,
                    showLegend: false,
                    smoothingIntervals: 1,
                },
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: experiment.filters?.events?.[0]?.name,
                        math: BaseMathType.UniqueUsers,
                        properties: [
                            {
                                key: `$feature/${experiment.feature_flag_key}`,
                                value: variants,
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    },
                ],
                breakdownFilter: {
                    breakdown: `$feature/${experiment.feature_flag_key}`,
                    breakdown_type: 'event',
                },
            },
        }
    }

    return (
        <div>
            <div className="flex space-x-2 items-center mb-2">
                <h2 className="font-semibold text-lg mb-0">Cumulative exposures</h2>
                <Tooltip title="Monitor number of unique users exposed to the experiment, and confirm the allocation matches the expected distribution between variants.">
                    <IconInfo className="text-muted-alt text-base" />
                </Tooltip>
            </div>
            {experiment.start_date ? (
                <InsightViz
                    query={{
                        ...query,
                        showTable: true,
                    }}
                    setQuery={() => {}}
                    readOnly
                    context={{
                        emptyStateHeading: 'No exposures to show yet',
                        emptyStateDetail: 'Hold tight! The chart will appear once some events are processed.',
                    }}
                />
            ) : (
                <div className="border rounded bg-bg-light">
                    <InsightEmptyState
                        heading="No exposures to show yet"
                        detail="This chart will display once the experiment starts."
                    />
                </div>
            )}
        </div>
    )
}
