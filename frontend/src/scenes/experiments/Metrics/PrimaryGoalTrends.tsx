import { LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { Query } from '~/queries/Query/Query'
import { ExperimentTrendsQuery, NodeKind } from '~/queries/schema'
import { FilterType, PropertyMathType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { commonActionFilterProps } from './Selectors'

export function PrimaryGoalTrends(): JSX.Element {
    const { experiment, isExperimentRunning, editingPrimaryMetricIndex } = useValues(experimentLogic)
    const { setTrendsMetric } = useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    if (!editingPrimaryMetricIndex && editingPrimaryMetricIndex !== 0) {
        return <></>
    }

    const metricIdx = editingPrimaryMetricIndex
    const currentMetric = experiment.metrics[metricIdx] as ExperimentTrendsQuery

    return (
        <>
            <div className="mb-4">
                <LemonLabel>Name (optional)</LemonLabel>
                <LemonInput
                    value={currentMetric.name}
                    onChange={(newName) => {
                        setTrendsMetric({
                            metricIdx,
                            name: newName,
                        })
                    }}
                />
            </div>
            <ActionFilter
                bordered
                filters={queryNodeToFilter(currentMetric.count_query)}
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    const series = actionsAndEventsToSeries(
                        { actions, events, data_warehouse } as any,
                        true,
                        MathAvailability.All
                    )

                    setTrendsMetric({
                        metricIdx,
                        series,
                    })
                }}
                typeKey="experiment-metric"
                buttonCopy="Add graph series"
                showSeriesIndicator={true}
                entitiesLimit={1}
                showNumericalPropsOnly={true}
                onlyPropertyMathDefinitions={[PropertyMathType.Average, PropertyMathType.Sum]}
                {...commonActionFilterProps}
            />
            <div className="mt-4 space-y-4">
                <TestAccountFilterSwitch
                    checked={hasFilters ? !!currentMetric.count_query?.filterTestAccounts : false}
                    onChange={(checked: boolean) => {
                        setTrendsMetric({
                            metricIdx,
                            filterTestAccounts: checked,
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
                        source: currentMetric.count_query,
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
