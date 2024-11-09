import './Experiment.scss'

import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
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

import { experimentLogic } from './experimentLogic'

export interface MetricSelectorProps {
    forceTrendExposureMetric?: boolean
}

export function PrimaryGoalTrends(): JSX.Element {
    const { experiment, isExperimentRunning, featureFlags } = useValues(experimentLogic)
    const { setExperiment, setTrendsMetric } = useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    return (
        <>
            <ActionFilter
                bordered
                filters={(() => {
                    // :FLAG: CLEAN UP AFTER MIGRATION
                    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                        return queryNodeToFilter((experiment.metrics[0] as ExperimentTrendsQuery).count_query)
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

                        setTrendsMetric({
                            metricIdx: 0,
                            series,
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
                // mathAvailability={isTrends ? undefined : MathAvailability.None}
                buttonCopy="Add graph series"
                showSeriesIndicator={true}
                entitiesLimit={1}
                // seriesIndicatorType={isTrends ? undefined : 'numeric'}
                // sortable={isTrends ? undefined : true}
                // showNestedArrow={isTrends ? undefined : true}
                showNumericalPropsOnly={true}
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
                <TestAccountFilterSwitch
                    checked={(() => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            const val = (experiment.metrics[0] as ExperimentTrendsQuery).count_query?.filterTestAccounts
                            return hasFilters ? !!val : false
                        }
                        return hasFilters ? !!experiment.filters.filter_test_accounts : false
                    })()}
                    onChange={(checked: boolean) => {
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setTrendsMetric({
                                metricIdx: 0,
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
                                return (experiment.metrics[0] as ExperimentTrendsQuery).count_query
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
