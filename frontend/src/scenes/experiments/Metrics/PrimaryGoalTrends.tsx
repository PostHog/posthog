import { LemonInput, LemonLabel } from '@posthog/lemon-ui'
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

export function PrimaryGoalTrends(): JSX.Element {
    const { experiment, isExperimentRunning, featureFlags, editingPrimaryMetricIndex } = useValues(experimentLogic)
    const { setExperiment, setTrendsMetric } = useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    if (!editingPrimaryMetricIndex && editingPrimaryMetricIndex !== 0) {
        console.warn('editingPrimaryMetricIndex is null or undefined')
        return <></>
    }

    const metricIdx = editingPrimaryMetricIndex
    const currentMetric = experiment.metrics[metricIdx] as ExperimentTrendsQuery
    // :FLAG: CLEAN UP AFTER MIGRATION
    const isDataWarehouseMetric =
        featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL] &&
        currentMetric.count_query.series[0].kind === NodeKind.DataWarehouseNode

    return (
        <>
            <div className="mb-4">
                <LemonLabel>Name (optional)</LemonLabel>
                {featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL] && (
                    <LemonInput
                        value={currentMetric.name}
                        onChange={(newName) => {
                            setTrendsMetric({
                                metricIdx,
                                name: newName,
                            })
                        }}
                    />
                )}
            </div>
            <ActionFilter
                bordered
                filters={(() => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        return queryNodeToFilter(currentMetric.count_query)
                    }
                    return experiment.filters
                })()}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        const series = actionsAndEventsToSeries(
                            { actions, events, data_warehouse } as any,
                            true,
                            MathAvailability.All
                        )

                        if (series[0].kind === NodeKind.DataWarehouseNode) {
                            setTrendsMetric({
                                metricIdx,
                                series,
                                filterTestAccounts: false,
                            })
                        } else {
                            setTrendsMetric({
                                metricIdx,
                                series,
                            })
                        }
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
                buttonCopy="Add graph series"
                showSeriesIndicator={true}
                entitiesLimit={1}
                showNumericalPropsOnly={true}
                {...commonActionFilterProps}
            />
            {!isDataWarehouseMetric && (
                <div className="mt-4 space-y-4">
                    <TestAccountFilterSwitch
                        checked={(() => {
                            // :FLAG: CLEAN UP AFTER MIGRATION
                            if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                const val = currentMetric.count_query?.filterTestAccounts
                                return hasFilters ? !!val : false
                            }
                            return hasFilters ? !!experiment.filters.filter_test_accounts : false
                        })()}
                        onChange={(checked: boolean) => {
                            // :FLAG: CLEAN UP AFTER MIGRATION
                            if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                setTrendsMetric({
                                    metricIdx,
                                    filterTestAccounts: checked,
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
            )}
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
                            return filtersToQueryNode(experiment.filters)
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
