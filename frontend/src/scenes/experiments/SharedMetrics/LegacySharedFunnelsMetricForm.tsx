import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { getHogQLValue } from 'scenes/insights/filters/AggregationSelect'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ExperimentFunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, FilterType } from '~/types'

import {
    FunnelAggregationSelect,
    FunnelAttributionSelect,
    FunnelConversionWindowFilter,
    commonActionFilterProps,
} from '../Metrics/Selectors'
import { sharedMetricLogic } from './sharedMetricLogic'

export function LegacySharedFunnelsMetricForm(): JSX.Element {
    const { sharedMetric } = useValues(sharedMetricLogic)
    const { setSharedMetric } = useActions(sharedMetricLogic)

    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    const actionFilterProps = {
        ...commonActionFilterProps,
        actionsTaxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    }

    if (!sharedMetric?.query) {
        return <></>
    }

    const sharedMetricQuery = sharedMetric.query as ExperimentFunnelsQuery

    return (
        <>
            <ActionFilter
                bordered
                filters={queryNodeToFilter(sharedMetricQuery.funnels_query)}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    if (!sharedMetric?.query) {
                        return
                    }

                    const series = actionsAndEventsToSeries(
                        { actions, events, data_warehouse } as any,
                        true,
                        MathAvailability.None
                    )
                    setSharedMetric({
                        query: {
                            ...sharedMetricQuery,
                            funnels_query: {
                                ...sharedMetricQuery.funnels_query,
                                series,
                            },
                        },
                    })
                }}
                typeKey="experiment-metric"
                mathAvailability={MathAvailability.None}
                buttonCopy="Add funnel step"
                showSeriesIndicator={true}
                seriesIndicatorType="numeric"
                sortable={true}
                showNestedArrow={true}
                {...actionFilterProps}
            />
            <div className="mt-4 deprecated-space-y-4">
                <FunnelAggregationSelect
                    value={getHogQLValue(
                        sharedMetricQuery.funnels_query.aggregation_group_type_index ?? undefined,
                        sharedMetricQuery.funnels_query.funnelsFilter?.funnelAggregateByHogQL ?? undefined
                    )}
                    onChange={(value) => {
                        setSharedMetric({
                            query: {
                                ...sharedMetricQuery,
                                funnels_query: {
                                    ...sharedMetricQuery.funnels_query,
                                    funnelsFilter: {
                                        ...sharedMetricQuery.funnels_query.funnelsFilter,
                                        funnelAggregateByHogQL: value,
                                    },
                                },
                            },
                        })
                    }}
                />
                <FunnelConversionWindowFilter
                    funnelWindowInterval={sharedMetricQuery.funnels_query?.funnelsFilter?.funnelWindowInterval}
                    funnelWindowIntervalUnit={sharedMetricQuery.funnels_query?.funnelsFilter?.funnelWindowIntervalUnit}
                    onFunnelWindowIntervalChange={(funnelWindowInterval) => {
                        setSharedMetric({
                            query: {
                                ...sharedMetricQuery,
                                funnels_query: {
                                    ...sharedMetricQuery.funnels_query,
                                    // funnelWindowInterval: funnelWindowInterval,
                                    funnelsFilter: {
                                        ...sharedMetricQuery.funnels_query.funnelsFilter,
                                        funnelWindowInterval: funnelWindowInterval,
                                    },
                                },
                            },
                        })
                    }}
                    onFunnelWindowIntervalUnitChange={(funnelWindowIntervalUnit) => {
                        setSharedMetric({
                            query: {
                                ...sharedMetricQuery,
                                funnels_query: {
                                    ...sharedMetricQuery.funnels_query,
                                    funnelsFilter: {
                                        ...sharedMetricQuery.funnels_query.funnelsFilter,
                                        funnelWindowIntervalUnit: funnelWindowIntervalUnit || undefined,
                                    },
                                },
                            },
                        })
                    }}
                />
                <FunnelAttributionSelect
                    value={(() => {
                        const breakdownAttributionType =
                            sharedMetricQuery.funnels_query?.funnelsFilter?.breakdownAttributionType
                        const breakdownAttributionValue =
                            sharedMetricQuery.funnels_query?.funnelsFilter?.breakdownAttributionValue

                        const currentValue: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}` =
                            !breakdownAttributionType
                                ? BreakdownAttributionType.FirstTouch
                                : breakdownAttributionType === BreakdownAttributionType.Step
                                  ? `${breakdownAttributionType}/${breakdownAttributionValue || 0}`
                                  : breakdownAttributionType

                        return currentValue
                    })()}
                    onChange={(value) => {
                        const [breakdownAttributionType, breakdownAttributionValue] = (value || '').split('/')
                        setSharedMetric({
                            query: {
                                ...sharedMetricQuery,
                                funnels_query: {
                                    ...sharedMetricQuery.funnels_query,
                                    funnelsFilter: {
                                        ...sharedMetricQuery.funnels_query.funnelsFilter,
                                        breakdownAttributionType: breakdownAttributionType as BreakdownAttributionType,
                                        breakdownAttributionValue: breakdownAttributionValue
                                            ? parseInt(breakdownAttributionValue)
                                            : undefined,
                                    },
                                },
                            },
                        })
                    }}
                    stepsLength={sharedMetricQuery.funnels_query?.series?.length}
                />
                <TestAccountFilterSwitch
                    checked={(() => {
                        const val = sharedMetricQuery.funnels_query?.filterTestAccounts
                        return hasFilters ? !!val : false
                    })()}
                    onChange={(checked: boolean) => {
                        setSharedMetric({
                            query: {
                                ...sharedMetricQuery,
                                funnels_query: {
                                    ...sharedMetricQuery.funnels_query,
                                    filterTestAccounts: checked,
                                },
                            },
                        })
                    }}
                    fullWidth
                />
            </div>

            <LemonBanner type="info" className="mt-3 mb-3">
                Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days of data. This can cause a
                mismatch between the preview and the actual results.
            </LemonBanner>

            <div className="mt-4">
                <Query
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: sharedMetricQuery.funnels_query,
                        showTable: false,
                        showLastComputation: true,
                        showLastComputationRefresh: false,
                    }}
                    readOnly
                />
            </div>
        </>
    )
}
