import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION, FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { getHogQLValue } from 'scenes/insights/filters/AggregationSelect'
import { teamLogic } from 'scenes/teamLogic'

import { actionsAndEventsToSeries, filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Query } from '~/queries/Query/Query'
import { ExperimentFunnelsQuery, NodeKind } from '~/queries/schema'
import { BreakdownAttributionType, FilterType, FunnelsFilterType } from '~/types'

import { MetricInsightId } from './constants'
import { experimentLogic } from './experimentLogic'
import { FunnelAggregationSelect, FunnelAttributionSelect, FunnelConversionWindowFilter } from './MetricSelector'

export function SecondaryGoalFunnels({ metricIdx }: { metricIdx: number }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { experiment, isExperimentRunning, featureFlags } = useValues(experimentLogic)
    const { setExperiment, setFunnelsMetric } = useActions(experimentLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const currentMetric = experiment.metrics_secondary[metricIdx] as ExperimentFunnelsQuery

    return (
        <>
            <ActionFilter
                bordered
                filters={(() => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        return queryNodeToFilter(currentMetric.funnels_query)
                    }
                    return experiment.filters
                })()}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        const series = actionsAndEventsToSeries(
                            { actions, events, data_warehouse } as any,
                            true,
                            MathAvailability.None
                        )

                        setFunnelsMetric({
                            metricIdx: 0,
                            series,
                            isSecondary: true,
                        })
                    } else {
                        if (actions?.length) {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    actions,
                                    events: undefined,
                                    data_warehouse: undefined,
                                },
                            })
                        } else if (events?.length) {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    events,
                                    actions: undefined,
                                    data_warehouse: undefined,
                                },
                            })
                        } else if (data_warehouse?.length) {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    data_warehouse,
                                    actions: undefined,
                                    events: undefined,
                                },
                            })
                        }
                    }
                }}
                typeKey="experiment-metric"
                mathAvailability={MathAvailability.None}
                buttonCopy="Add funnel step"
                showSeriesIndicator={true}
                seriesIndicatorType="numeric"
                sortable={true}
                showNestedArrow={true}
                actionsTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.DataWarehouse,
                ]}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                    TaxonomicFilterGroupType.DataWarehouseProperties,
                    TaxonomicFilterGroupType.DataWarehousePersonProperties,
                ]}
            />
            <div className="mt-4 space-y-4">
                <FunnelAggregationSelect
                    value={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            return getHogQLValue(
                                currentMetric.funnels_query.aggregation_group_type_index ?? undefined,
                                currentMetric.funnels_query.funnelsFilter?.funnelAggregateByHogQL ?? undefined
                            )
                        }
                        return getHogQLValue(
                            experiment.filters.aggregation_group_type_index,
                            (experiment.filters as FunnelsFilterType).funnel_aggregate_by_hogql
                        )
                    })()}
                    onChange={(value) => {
                        setFunnelsMetric({
                            metricIdx: 0,
                            funnelAggregateByHogQL: value,
                            isSecondary: true,
                        })
                    }}
                />
                <FunnelConversionWindowFilter
                    funnelWindowInterval={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            return currentMetric.funnels_query?.funnelsFilter?.funnelWindowInterval
                        }
                        return (experiment.filters as FunnelsFilterType).funnel_window_interval
                    })()}
                    funnelWindowIntervalUnit={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            return currentMetric.funnels_query?.funnelsFilter?.funnelWindowIntervalUnit
                        }
                        return (experiment.filters as FunnelsFilterType).funnel_window_interval_unit
                    })()}
                    onFunnelWindowIntervalChange={(funnelWindowInterval) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx: 0,
                                funnelWindowInterval: funnelWindowInterval,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    funnel_window_interval: funnelWindowInterval,
                                },
                            })
                        }
                    }}
                    onFunnelWindowIntervalUnitChange={(funnelWindowIntervalUnit) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx: 0,
                                funnelWindowIntervalUnit: funnelWindowIntervalUnit || undefined,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    funnel_window_interval_unit: funnelWindowIntervalUnit || undefined,
                                },
                            })
                        }
                    }}
                />
                <FunnelAttributionSelect
                    value={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        let breakdownAttributionType
                        let breakdownAttributionValue
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            breakdownAttributionType =
                                currentMetric.funnels_query?.funnelsFilter?.breakdownAttributionType
                            breakdownAttributionValue =
                                currentMetric.funnels_query?.funnelsFilter?.breakdownAttributionValue
                        } else {
                            breakdownAttributionType = (experiment.filters as FunnelsFilterType)
                                .breakdown_attribution_type
                            breakdownAttributionValue = (experiment.filters as FunnelsFilterType)
                                .breakdown_attribution_value
                        }

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
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx: 0,
                                breakdownAttributionType: breakdownAttributionType as BreakdownAttributionType,
                                breakdownAttributionValue: breakdownAttributionValue
                                    ? parseInt(breakdownAttributionValue)
                                    : undefined,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    breakdown_attribution_type: breakdownAttributionType as BreakdownAttributionType,
                                    breakdown_attribution_value: breakdownAttributionValue
                                        ? parseInt(breakdownAttributionValue)
                                        : 0,
                                },
                            })
                        }
                    }}
                    stepsLength={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            return currentMetric.funnels_query?.series?.length
                        }
                        return Math.max(
                            experiment.filters.actions?.length ?? 0,
                            experiment.filters.events?.length ?? 0,
                            experiment.filters.data_warehouse?.length ?? 0
                        )
                    })()}
                />
                <TestAccountFilterSwitch
                    checked={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            const val = (experiment.metrics[0] as ExperimentFunnelsQuery).funnels_query
                                ?.filterTestAccounts
                            return hasFilters ? !!val : false
                        }
                        return hasFilters ? !!experiment.filters.filter_test_accounts : false
                    })()}
                    onChange={(checked: boolean) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx: 0,
                                filterTestAccounts: checked,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    filter_test_accounts: checked,
                                },
                            })
                        }
                    }}
                    fullWidth
                />
            </div>
            {isExperimentRunning && (
                <LemonBanner type="info" className="mt-3 mb-3">
                    Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days of data. This can cause a
                    mismatch between the preview and the actual results.
                </LemonBanner>
            )}
            <div className="mt-4">
                {/* :FLAG: CLEAN UP AFTER MIGRATION */}
                <Query
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: (() => {
                            // :FLAG: CLEAN UP AFTER MIGRATION
                            if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                return currentMetric.funnels_query
                            }
                            return filtersToQueryNode(experiment.filters)
                        })(),
                        showTable: false,
                        showLastComputation: true,
                        showLastComputationRefresh: false,
                    }}
                    readOnly
                    context={{
                        insightProps: {
                            dashboardItemId: MetricInsightId.Funnels,
                        },
                    }}
                />
            </div>
        </>
    )
}
