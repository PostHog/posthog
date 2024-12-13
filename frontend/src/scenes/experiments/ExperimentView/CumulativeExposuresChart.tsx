import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { InsightViz } from '~/queries/nodes/InsightViz/InsightViz'
import { queryFromFilters } from '~/queries/nodes/InsightViz/utils'
import { CachedExperimentTrendsQueryResponse, InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema'
import {
    _TrendsExperimentResults,
    BaseMathType,
    ChartDisplayType,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { experimentLogic } from '../experimentLogic'
import { transformResultFilters } from '../utils'

export function CumulativeExposuresChart(): JSX.Element {
    const { experiment, experimentResults, getMetricType } = useValues(experimentLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const metricIdx = 0
    const metricType = getMetricType(metricIdx)

    const variants = experiment.parameters?.feature_flag_variants?.map((variant) => variant.key) || []
    if (experiment.holdout) {
        variants.push(`holdout-${experiment.holdout.id}`)
    }

    let query

    // :FLAG: CLEAN UP AFTER MIGRATION
    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
        if (metricType === InsightType.TRENDS) {
            query = {
                kind: NodeKind.InsightVizNode,
                source: (experimentResults as CachedExperimentTrendsQueryResponse).exposure_query,
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
    } else {
        if (metricType === InsightType.TRENDS && experiment.parameters?.custom_exposure_filter) {
            const trendResults = experimentResults as _TrendsExperimentResults
            const queryFilters = {
                ...trendResults.exposure_filters,
                display: ChartDisplayType.ActionsLineGraphCumulative,
            } as _TrendsExperimentResults['exposure_filters']
            query = queryFromFilters(transformResultFilters(queryFilters))
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
                            event:
                                metricType === InsightType.TRENDS
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
    }

    return (
        <div>
            <div className="flex space-x-2 items-center mb-2">
                <h2 className="font-semibold text-lg mb-0">Cumulative exposures</h2>
                <Tooltip title="Monitor number of unique users exposed to the experiment, and confirm the allocation matches the expected distribution between variants.">
                    <IconInfo className="content-tertiary text-base" />
                </Tooltip>
            </div>
            {experiment.start_date ? (
                <InsightViz
                    query={{
                        ...(query as InsightVizNode<InsightQueryNode>),
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
                <div className="border rounded background-primary">
                    <InsightEmptyState
                        heading="No exposures to show yet"
                        detail="This chart will display once the experiment starts."
                    />
                </div>
            )}
        </div>
    )
}
