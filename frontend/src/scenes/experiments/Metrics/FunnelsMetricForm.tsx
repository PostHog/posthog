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
import { ExperimentFunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import {
    commonActionFilterProps,
    FunnelAggregationSelect,
    FunnelAttributionSelect,
    FunnelConversionWindowFilter,
} from './Selectors'
export function FunnelsMetricForm({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { experiment, isExperimentRunning, editingPrimaryMetricIndex, editingSecondaryMetricIndex } =
        useValues(experimentLogic)
    const { setFunnelsMetric } = useActions(experimentLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const metricIdx = isSecondary ? editingSecondaryMetricIndex : editingPrimaryMetricIndex

    if (!metricIdx && metricIdx !== 0) {
        return <></>
    }

    const currentMetric = metrics[metricIdx] as ExperimentFunnelsQuery

    const actionFilterProps = {
        ...commonActionFilterProps,
        actionsTaxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    }

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
                            isSecondary,
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
                        isSecondary,
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
            <div className="mt-4 deprecated-space-y-4">
                <FunnelAggregationSelect
                    value={getHogQLValue(
                        currentMetric.funnels_query.aggregation_group_type_index ?? undefined,
                        currentMetric.funnels_query.funnelsFilter?.funnelAggregateByHogQL ?? undefined
                    )}
                    onChange={(value) => {
                        setFunnelsMetric({
                            metricIdx,
                            funnelAggregateByHogQL: value,
                            isSecondary,
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
                            isSecondary,
                        })
                    }}
                    onFunnelWindowIntervalUnitChange={(funnelWindowIntervalUnit) => {
                        setFunnelsMetric({
                            metricIdx,
                            funnelWindowIntervalUnit: funnelWindowIntervalUnit || undefined,
                            isSecondary,
                        })
                    }}
                />
                <FunnelAttributionSelect
                    value={(() => {
                        const breakdownAttributionType =
                            currentMetric.funnels_query?.funnelsFilter?.breakdownAttributionType
                        const breakdownAttributionValue =
                            currentMetric.funnels_query?.funnelsFilter?.breakdownAttributionValue

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
                        setFunnelsMetric({
                            metricIdx,
                            breakdownAttributionType: breakdownAttributionType as BreakdownAttributionType,
                            breakdownAttributionValue: breakdownAttributionValue
                                ? parseInt(breakdownAttributionValue)
                                : undefined,
                            isSecondary,
                        })
                    }}
                    stepsLength={currentMetric.funnels_query?.series?.length}
                />
                <TestAccountFilterSwitch
                    checked={(() => {
                        const val = currentMetric.funnels_query?.filterTestAccounts
                        return hasFilters ? !!val : false
                    })()}
                    onChange={(checked: boolean) => {
                        setFunnelsMetric({
                            metricIdx,
                            filterTestAccounts: checked,
                            isSecondary,
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
