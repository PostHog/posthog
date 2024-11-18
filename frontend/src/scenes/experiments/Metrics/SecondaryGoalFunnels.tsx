import { LemonLabel } from '@posthog/lemon-ui'
import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
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

import { experimentLogic } from '../experimentLogic'
import {
    commonActionFilterProps,
    FunnelAggregationSelect,
    FunnelAttributionSelect,
    FunnelConversionWindowFilter,
} from './Selectors'

export function SecondaryGoalFunnels({ metricIdx }: { metricIdx: number }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { experiment, isExperimentRunning, featureFlags } = useValues(experimentLogic)
    const { setExperiment, setFunnelsMetric } = useActions(experimentLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const currentMetric = experiment.metrics_secondary[metricIdx] as ExperimentFunnelsQuery

    return (
        <>
            <div className="mb-4">
                <LemonLabel>Name (optional)</LemonLabel>
                <LemonInput
                    value={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            return currentMetric.name
                        }
                        return experiment.secondary_metrics[metricIdx].name
                    })()}
                    onChange={(newName) => {
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx,
                                name: newName,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx ? { ...metric, name: newName } : metric
                                ),
                            })
                        }
                    }}
                />
            </div>
            <ActionFilter
                bordered
                filters={(() => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        return queryNodeToFilter(currentMetric.funnels_query)
                    }
                    return experiment.secondary_metrics[metricIdx].filters
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
                            metricIdx,
                            series,
                            isSecondary: true,
                        })
                    } else {
                        if (actions?.length) {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx
                                        ? {
                                              ...metric,
                                              filters: {
                                                  ...metric.filters,
                                                  actions,
                                                  events: undefined,
                                                  data_warehouse: undefined,
                                              },
                                          }
                                        : metric
                                ),
                            })
                        } else if (events?.length) {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx
                                        ? {
                                              ...metric,
                                              filters: {
                                                  ...metric.filters,
                                                  events,
                                                  actions: undefined,
                                                  data_warehouse: undefined,
                                              },
                                          }
                                        : metric
                                ),
                            })
                        } else if (data_warehouse?.length) {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx
                                        ? {
                                              ...metric,
                                              filters: {
                                                  ...metric.filters,
                                                  data_warehouse,
                                                  actions: undefined,
                                                  events: undefined,
                                              },
                                          }
                                        : metric
                                ),
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
                {...commonActionFilterProps}
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
                            experiment.secondary_metrics[metricIdx].filters.aggregation_group_type_index,
                            (experiment.secondary_metrics[metricIdx].filters as FunnelsFilterType)
                                .funnel_aggregate_by_hogql
                        )
                    })()}
                    onChange={(value) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx,
                                funnelAggregateByHogQL: value,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx
                                        ? {
                                              ...metric,
                                              filters: {
                                                  ...metric.filters,
                                                  funnel_aggregate_by_hogql: value,
                                              },
                                          }
                                        : metric
                                ),
                            })
                        }
                    }}
                />
                <FunnelConversionWindowFilter
                    funnelWindowInterval={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            return currentMetric.funnels_query?.funnelsFilter?.funnelWindowInterval
                        }
                        return (experiment.secondary_metrics[metricIdx].filters as FunnelsFilterType)
                            .funnel_window_interval
                    })()}
                    funnelWindowIntervalUnit={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            return currentMetric.funnels_query?.funnelsFilter?.funnelWindowIntervalUnit
                        }
                        return (experiment.secondary_metrics[metricIdx].filters as FunnelsFilterType)
                            .funnel_window_interval_unit
                    })()}
                    onFunnelWindowIntervalChange={(funnelWindowInterval) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx,
                                funnelWindowInterval: funnelWindowInterval,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx
                                        ? {
                                              ...metric,
                                              filters: {
                                                  ...metric.filters,
                                                  funnel_window_interval: funnelWindowInterval,
                                              },
                                          }
                                        : metric
                                ),
                            })
                        }
                    }}
                    onFunnelWindowIntervalUnitChange={(funnelWindowIntervalUnit) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx,
                                funnelWindowIntervalUnit: funnelWindowIntervalUnit || undefined,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx
                                        ? {
                                              ...metric,
                                              filters: {
                                                  ...metric.filters,
                                                  funnel_window_interval_unit: funnelWindowIntervalUnit || undefined,
                                              },
                                          }
                                        : metric
                                ),
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
                            breakdownAttributionType = (
                                experiment.secondary_metrics[metricIdx].filters as FunnelsFilterType
                            ).breakdown_attribution_type
                            breakdownAttributionValue = (
                                experiment.secondary_metrics[metricIdx].filters as FunnelsFilterType
                            ).breakdown_attribution_value
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
                                metricIdx,
                                breakdownAttributionType: breakdownAttributionType as BreakdownAttributionType,
                                breakdownAttributionValue: breakdownAttributionValue
                                    ? parseInt(breakdownAttributionValue)
                                    : undefined,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx
                                        ? {
                                              ...metric,
                                              filters: {
                                                  ...metric.filters,
                                                  breakdown_attribution_type:
                                                      breakdownAttributionType as BreakdownAttributionType,
                                                  breakdown_attribution_value: breakdownAttributionValue
                                                      ? parseInt(breakdownAttributionValue)
                                                      : 0,
                                              },
                                          }
                                        : metric
                                ),
                            })
                        }
                    }}
                    stepsLength={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            return currentMetric.funnels_query?.series?.length
                        }
                        return Math.max(
                            experiment.secondary_metrics[metricIdx].filters.actions?.length ?? 0,
                            experiment.secondary_metrics[metricIdx].filters.events?.length ?? 0,
                            experiment.secondary_metrics[metricIdx].filters.data_warehouse?.length ?? 0
                        )
                    })()}
                />
                <TestAccountFilterSwitch
                    checked={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            const val = (experiment.metrics_secondary[metricIdx] as ExperimentFunnelsQuery)
                                .funnels_query?.filterTestAccounts
                            return hasFilters ? !!val : false
                        }
                        return hasFilters
                            ? !!experiment.secondary_metrics[metricIdx].filters.filter_test_accounts
                            : false
                    })()}
                    onChange={(checked: boolean) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setFunnelsMetric({
                                metricIdx,
                                filterTestAccounts: checked,
                                isSecondary: true,
                            })
                        } else {
                            setExperiment({
                                secondary_metrics: experiment.secondary_metrics.map((metric, idx) =>
                                    idx === metricIdx
                                        ? {
                                              ...metric,
                                              filters: {
                                                  ...metric.filters,
                                                  filter_test_accounts: checked,
                                              },
                                          }
                                        : metric
                                ),
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
                            return filtersToQueryNode(experiment.secondary_metrics[metricIdx].filters)
                        })(),
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
