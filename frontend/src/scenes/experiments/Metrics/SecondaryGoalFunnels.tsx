import { LemonLabel } from '@posthog/lemon-ui'
import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
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
    const { experiment, isExperimentRunning } = useValues(experimentLogic)
    const { setExperiment, setFunnelsMetric } = useActions(experimentLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const currentMetric = experiment.metrics_secondary[metricIdx] as ExperimentFunnelsQuery

    return (
        <>
            <div className="mb-4">
                <LemonLabel>Name (optional)</LemonLabel>
                <LemonInput
                    value={currentMetric.name}
                    onChange={(newName) => {
                        setFunnelsMetric({
                            metricIdx,
                            name: newName,
                            isSecondary: true,
                        })
                    }}
                />
            </div>
            <ActionFilter
                bordered
                filters={queryNodeToFilter(currentMetric.funnels_query)}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
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
                    value={getHogQLValue(
                        currentMetric.funnels_query.aggregation_group_type_index ?? undefined,
                        currentMetric.funnels_query.funnelsFilter?.funnelAggregateByHogQL ?? undefined
                    )}
                    onChange={(value) => {
                        setFunnelsMetric({
                            metricIdx,
                            funnelAggregateByHogQL: value,
                            isSecondary: true,
                        })
                    }}
                />
                <FunnelConversionWindowFilter
                    funnelWindowInterval={currentMetric.funnels_query?.funnelsFilter?.funnelWindowInterval}
                    funnelWindowIntervalUnit={currentMetric.funnels_query?.funnelsFilter?.funnelWindowIntervalUnit}
                    onFunnelWindowIntervalChange={(funnelWindowInterval) => {
                        setFunnelsMetric({
                            metricIdx,
                            funnelWindowInterval: funnelWindowInterval,
                            isSecondary: true,
                        })
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
                    checked={hasFilters ? !!currentMetric.funnels_query?.filterTestAccounts : false}
                    onChange={(checked: boolean) => {
                        setFunnelsMetric({
                            metricIdx,
                            filterTestAccounts: checked,
                            isSecondary: true,
                        })
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
            </div>
        </>
    )
}
