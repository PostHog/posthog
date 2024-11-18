import { LemonLabel } from '@posthog/lemon-ui'
import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION, FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { actionsAndEventsToSeries, filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Query } from '~/queries/Query/Query'
import { ExperimentTrendsQuery, NodeKind } from '~/queries/schema'
import { FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { commonActionFilterProps } from './Selectors'

export function SecondaryGoalTrends({ metricIdx }: { metricIdx: number }): JSX.Element {
    const { experiment, isExperimentRunning, featureFlags } = useValues(experimentLogic)
    const { setExperiment, setTrendsMetric } = useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const currentMetric = experiment.metrics_secondary[metricIdx] as ExperimentTrendsQuery

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
                            setTrendsMetric({
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
                        return queryNodeToFilter(currentMetric.count_query)
                    }
                    return experiment.secondary_metrics[metricIdx].filters
                })()}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        const series = actionsAndEventsToSeries(
                            { actions, events, data_warehouse } as any,
                            true,
                            MathAvailability.All
                        )

                        setTrendsMetric({
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
                buttonCopy="Add graph series"
                showSeriesIndicator={true}
                entitiesLimit={1}
                showNumericalPropsOnly={true}
                {...commonActionFilterProps}
            />
            <div className="mt-4 space-y-4">
                <TestAccountFilterSwitch
                    checked={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            const val = currentMetric.count_query?.filterTestAccounts
                            return hasFilters ? !!val : false
                        }
                        return hasFilters
                            ? !!experiment.secondary_metrics[metricIdx].filters.filter_test_accounts
                            : false
                    })()}
                    onChange={(checked: boolean) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setTrendsMetric({
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
                                return currentMetric.count_query
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
