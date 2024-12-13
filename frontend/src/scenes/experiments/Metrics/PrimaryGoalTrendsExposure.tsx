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
import { ExperimentTrendsQuery, InsightQueryNode, NodeKind } from '~/queries/schema'
import { FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { commonActionFilterProps } from './Selectors'

export function PrimaryGoalTrendsExposure(): JSX.Element {
    const { experiment, isExperimentRunning, featureFlags, editingPrimaryMetricIndex } = useValues(experimentLogic)
    const { setExperiment, setTrendsExposureMetric } = useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    if (!editingPrimaryMetricIndex && editingPrimaryMetricIndex !== 0) {
        console.warn('editingPrimaryMetricIndex is null or undefined')
        return <></>
    }

    const currentMetric = experiment.metrics[editingPrimaryMetricIndex] as ExperimentTrendsQuery

    return (
        <>
            <ActionFilter
                bordered
                filters={(() => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        return queryNodeToFilter(currentMetric.exposure_query as InsightQueryNode)
                    }
                    return experiment.parameters.custom_exposure_filter as FilterType
                })()}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        const series = actionsAndEventsToSeries(
                            { actions, events, data_warehouse } as any,
                            true,
                            MathAvailability.All
                        )

                        setTrendsExposureMetric({
                            metricIdx: editingPrimaryMetricIndex,
                            series,
                        })
                    } else {
                        if (actions?.length) {
                            setExperiment({
                                parameters: {
                                    ...experiment.parameters,
                                    custom_exposure_filter: {
                                        ...experiment.parameters.custom_exposure_filter,
                                        actions,
                                        events: undefined,
                                        data_warehouse: undefined,
                                    },
                                },
                            })
                        } else if (events?.length) {
                            setExperiment({
                                parameters: {
                                    ...experiment.parameters,
                                    custom_exposure_filter: {
                                        ...experiment.parameters.custom_exposure_filter,
                                        events,
                                        actions: undefined,
                                        data_warehouse: undefined,
                                    },
                                },
                            })
                        } else if (data_warehouse?.length) {
                            setExperiment({
                                parameters: {
                                    ...experiment.parameters,
                                    custom_exposure_filter: {
                                        ...experiment.parameters.custom_exposure_filter,
                                        data_warehouse,
                                        actions: undefined,
                                        events: undefined,
                                    },
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
            <div className="mt-4 space-y-4">
                <TestAccountFilterSwitch
                    checked={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            const val = currentMetric.exposure_query?.filterTestAccounts
                            return hasFilters ? !!val : false
                        }
                        return hasFilters
                            ? !!(experiment.parameters.custom_exposure_filter as FilterType).filter_test_accounts
                            : false
                    })()}
                    onChange={(checked: boolean) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setTrendsExposureMetric({
                                metricIdx: editingPrimaryMetricIndex,
                                filterTestAccounts: checked,
                            })
                        } else {
                            setExperiment({
                                parameters: {
                                    ...experiment.parameters,
                                    custom_exposure_filter: {
                                        ...experiment.parameters.custom_exposure_filter,
                                        filter_test_accounts: checked,
                                    },
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
                                return currentMetric.exposure_query
                            }
                            return filtersToQueryNode(experiment.parameters.custom_exposure_filter as FilterType)
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
