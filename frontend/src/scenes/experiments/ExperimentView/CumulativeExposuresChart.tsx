import { useValues } from 'kea'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema'
import { BaseMathType, ChartDisplayType, Experiment, InsightType } from '~/types'

import { experimentLogic } from '../experimentLogic'

const getCumulativeExposuresQuery = (experiment: Experiment): InsightVizNode<TrendsQuery> => {
    const experimentInsightType = experiment.filters?.insight || InsightType.TRENDS

    // Trends Experiment
    if (experimentInsightType === InsightType.TRENDS) {
        const exposureName = experiment.parameters?.custom_exposure_filter?.events?.[0]?.name
        const eventName = exposureName ?? '$feature_flag_called'
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
                    showLegend: true,
                    smoothingIntervals: 1,
                },
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: eventName,
                        math: BaseMathType.UniqueUsers,
                    },
                ],
                breakdownFilter: exposureName
                    ? {
                          breakdown: exposureName,
                          breakdown_type: 'event',
                      }
                    : undefined,
            },
        }
    }
    // Funnel Experiment
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
                showLegend: true,
                smoothingIntervals: 1,
            },
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: experiment.filters?.events?.[0]?.name,
                    math: BaseMathType.UniqueUsers,
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
                <Query
                    query={getCumulativeExposuresQuery(experiment)}
                    readOnly
                    context={{
                        emptyStateHeading: 'No exposures to cumulate yet',
                        emptyStateDetail: 'Hold tight! The chart will appear once some events are processed.',
                    }}
                />
            ) : (
                <div className="border rounded bg-bg-light">
                    <InsightEmptyState
                        heading="No exposures to cumulate yet"
                        detail="This chart will display once the experiment starts."
                    />
                </div>
            )}
        </div>
    )
}
