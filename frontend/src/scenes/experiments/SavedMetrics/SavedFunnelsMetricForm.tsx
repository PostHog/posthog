import { LemonLabel } from '@posthog/lemon-ui'
import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { getHogQLValue } from 'scenes/insights/filters/AggregationSelect'
import { teamLogic } from 'scenes/teamLogic'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Query } from '~/queries/Query/Query'
import { ExperimentFunnelsQuery, NodeKind } from '~/queries/schema'
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
                filters={queryNodeToFilter(savedMetric.query.funnels_query)}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    const series = actionsAndEventsToSeries(
                        { actions, events, data_warehouse } as any,
                        true,
                        MathAvailability.None
                    )
                    setSavedMetric({
                        query: {
                            ...savedMetric.query,
                            funnels_query: {
                                ...savedMetric.query.funnels_query,
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
                        savedMetric.query.funnels_query.aggregation_group_type_index ?? undefined,
                        savedMetric.query.funnels_query.funnelsFilter?.funnelAggregateByHogQL ?? undefined
                    )}
                    onChange={(value) => {
                        setSavedMetric({
                            query: {
                                ...savedMetric.query,
                                funnels_query: {
                                    ...savedMetric.query.funnels_query,
                                    aggregation_group_type_index: value,
                                },
                            },
                        })
                    }}
                />
                <FunnelConversionWindowFilter
                    funnelWindowInterval={savedMetric.query.funnels_query?.funnelsFilter?.funnelWindowInterval}
                    funnelWindowIntervalUnit={savedMetric.query.funnels_query?.funnelsFilter?.funnelWindowIntervalUnit}
                    onFunnelWindowIntervalChange={(funnelWindowInterval) => {
                        setSavedMetric({
                            query: {
                                ...savedMetric.query,
                                funnels_query: {
                                    ...savedMetric.query.funnels_query,
                                    // funnelWindowInterval: funnelWindowInterval,
                                    funnelsFilter: {
                                        ...savedMetric.query.funnels_query.funnelsFilter,
                                        funnelWindowInterval: funnelWindowInterval,
                                    },
                                },
                            },
                        })
                    }}
                    onFunnelWindowIntervalUnitChange={(funnelWindowIntervalUnit) => {
                        setSavedMetric({
                            query: {
                                ...savedMetric.query,
                                funnels_query: {
                                    ...savedMetric.query.funnels_query,
                                    funnelsFilter: {
                                        ...savedMetric.query.funnels_query.funnelsFilter,
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
                            savedMetric.query.funnels_query?.funnelsFilter?.breakdownAttributionType
                        const breakdownAttributionValue =
                            savedMetric.query.funnels_query?.funnelsFilter?.breakdownAttributionValue

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
                                ...savedMetric.query,
                                funnels_query: {
                                    ...savedMetric.query.funnels_query,
                                    funnelsFilter: {
                                        ...savedMetric.query.funnels_query.funnelsFilter,
                                        breakdownAttributionType: breakdownAttributionType as BreakdownAttributionType,
                                        breakdownAttributionValue: breakdownAttributionValue
                                            ? parseInt(breakdownAttributionValue)
                                            : undefined,
                                    },
                                },
                            },
                        })
                    }}
                    stepsLength={savedMetric.query.funnels_query?.series?.length}
                />
                <TestAccountFilterSwitch
                    checked={(() => {
                        const val = savedMetric.query.funnels_query?.filterTestAccounts
                        return hasFilters ? !!val : false
                    })()}
                    onChange={(checked: boolean) => {
                        setSavedMetric({
                            query: {
                                ...savedMetric.query,
                                funnels_query: {
                                    ...savedMetric.query.funnels_query,
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
