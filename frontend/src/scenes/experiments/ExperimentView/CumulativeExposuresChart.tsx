import { useValues } from 'kea'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { InsightViz } from '~/queries/nodes/InsightViz/InsightViz'
import { queryFromFilters } from '~/queries/nodes/InsightViz/utils'
import { InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema'
import { BaseMathType, ChartDisplayType, Experiment, InsightType, PropertyFilterType, PropertyOperator } from '~/types'

import { experimentLogic } from '../experimentLogic'

const getCumulativeExposuresQuery = (experiment: Experiment): InsightVizNode<InsightQueryNode> => {
    const experimentInsightType = experiment.filters?.insight || InsightType.TRENDS

    const variants = experiment.parameters?.feature_flag_variants?.map((variant) => variant.key) || []
    if (experiment.holdout) {
        variants.push(`holdout-${experiment.holdout.id}`)
    }

    // Trends Experiment
    if (experimentInsightType === InsightType.TRENDS && experiment.parameters?.custom_exposure_filter) {
        const queryFilters = {
            ...experiment.parameters?.custom_exposure_filter,
            display: ChartDisplayType.ActionsLineGraphCumulative,
        }
        return queryFromFilters(queryFilters)
    }
    return {
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
                    event:
                        experimentInsightType === InsightType.TRENDS
                            ? '$feature_flag_called'
                            : experiment.filters?.events?.[0]?.name,
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

export function CumulativeExposuresChart(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    return (
        <div>
            <div>
                <h2 className="font-semibold text-lg">Cumulative exposures</h2>
            </div>
            {experiment.start_date ? (
                <InsightViz
                    query={{
                        ...getCumulativeExposuresQuery(experiment),
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
