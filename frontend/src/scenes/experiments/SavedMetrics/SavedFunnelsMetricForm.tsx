import { LemonLabel } from '@posthog/lemon-ui'
import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { getHogQLValue } from 'scenes/insights/filters/AggregationSelect'
import { teamLogic } from 'scenes/teamLogic'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ExperimentFunnelsQuery } from '~/queries/schema'
import { BreakdownAttributionType, FilterType } from '~/types'

import {
    commonActionFilterProps,
    FunnelAggregationSelect,
    FunnelAttributionSelect,
    FunnelConversionWindowFilter,
} from '../Metrics/Selectors'
import { savedMetricLogic } from './savedMetricLogic'

export function SavedFunnelsMetricForm(): JSX.Element {
    const { savedMetric } = useValues(savedMetricLogic)
    const { setSavedMetric } = useActions(savedMetricLogic)

    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    const actionFilterProps = {
        ...commonActionFilterProps,
        actionsTaxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    }

    if (!savedMetric?.query) {
        return <></>
    }

    const savedMetricQuery = savedMetric.query as ExperimentFunnelsQuery

    return (
        <>
            <div className="mb-4">
                <LemonLabel>Name (optional)</LemonLabel>
                <LemonInput
                    // TODO: use correct field!!!
                    value={savedMetric.name}
                    onChange={(newName) => {
                        setSavedMetric({
                            name: newName,
                        })
                    }}
                />
            </div>
            <ActionFilter
                bordered
                filters={queryNodeToFilter(savedMetricQuery.funnels_query)}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    if (!savedMetric?.query) {
                        return
                    }

                    const series = actionsAndEventsToSeries(
                        { actions, events, data_warehouse } as any,
                        true,
                        MathAvailability.None
                    )
                    setSavedMetric({
                        query: {
                            ...savedMetricQuery,
                            funnels_query: {
                                ...savedMetricQuery.funnels_query,
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
            <div className="mt-4 space-y-4">
                <FunnelAggregationSelect
                    value={getHogQLValue(
                        savedMetricQuery.funnels_query.aggregation_group_type_index ?? undefined,
                        savedMetricQuery.funnels_query.funnelsFilter?.funnelAggregateByHogQL ?? undefined
                    )}
                    onChange={(value) => {
                        setSavedMetric({
                            query: {
                                ...savedMetricQuery,
                                funnels_query: {
                                    ...savedMetricQuery.funnels_query,
                                    aggregation_group_type_index: value,
                                },
                            },
                        })
                    }}
                />
                <FunnelConversionWindowFilter
                    funnelWindowInterval={savedMetricQuery.funnels_query?.funnelsFilter?.funnelWindowInterval}
                    funnelWindowIntervalUnit={savedMetricQuery.funnels_query?.funnelsFilter?.funnelWindowIntervalUnit}
                    onFunnelWindowIntervalChange={(funnelWindowInterval) => {
                        setSavedMetric({
                            query: {
                                ...savedMetricQuery,
                                funnels_query: {
                                    ...savedMetricQuery.funnels_query,
                                    // funnelWindowInterval: funnelWindowInterval,
                                    funnelsFilter: {
                                        ...savedMetricQuery.funnels_query.funnelsFilter,
                                        funnelWindowInterval: funnelWindowInterval,
                                    },
                                },
                            },
                        })
                    }}
                    onFunnelWindowIntervalUnitChange={(funnelWindowIntervalUnit) => {
                        setSavedMetric({
                            query: {
                                ...savedMetricQuery,
                                funnels_query: {
                                    ...savedMetricQuery.funnels_query,
                                    funnelsFilter: {
                                        ...savedMetricQuery.funnels_query.funnelsFilter,
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
                            savedMetricQuery.funnels_query?.funnelsFilter?.breakdownAttributionType
                        const breakdownAttributionValue =
                            savedMetricQuery.funnels_query?.funnelsFilter?.breakdownAttributionValue

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
                        setSavedMetric({
                            query: {
                                ...savedMetricQuery,
                                funnels_query: {
                                    ...savedMetricQuery.funnels_query,
                                    funnelsFilter: {
                                        ...savedMetricQuery.funnels_query.funnelsFilter,
                                        breakdownAttributionType: breakdownAttributionType as BreakdownAttributionType,
                                        breakdownAttributionValue: breakdownAttributionValue
                                            ? parseInt(breakdownAttributionValue)
                                            : undefined,
                                    },
                                },
                            },
                        })
                    }}
                    stepsLength={savedMetricQuery.funnels_query?.series?.length}
                />
                <TestAccountFilterSwitch
                    checked={(() => {
                        const val = savedMetricQuery.funnels_query?.filterTestAccounts
                        return hasFilters ? !!val : false
                    })()}
                    onChange={(checked: boolean) => {
                        setSavedMetric({
                            query: {
                                ...savedMetricQuery,
                                funnels_query: {
                                    ...savedMetricQuery.funnels_query,
                                    filterTestAccounts: checked,
                                },
                            },
                        })
                    }}
                    fullWidth
                />
            </div>
            {/* {isExperimentRunning && (
                <LemonBanner type="info" className="mt-3 mb-3">
                    Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days of data. This can cause a
                    mismatch between the preview and the actual results.
                </LemonBanner>
            )} */}
            {/* <div className="mt-4">
                <Query
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: currentMetric.funnels_query,
                        showTable: false,
                        showLastComputation: true,
                        showLastComputationRefresh: false,
                    }}
                    readOnly
                />
            </div> */}
        </>
    )
}
