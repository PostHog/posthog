import { useActions, useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'
import { LemonInput } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { getHogQLValue } from 'scenes/insights/filters/AggregationSelect'
import { teamLogic } from 'scenes/teamLogic'

import { Query } from '~/queries/Query/Query'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { ExperimentFunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import {
    FunnelAggregationSelect,
    FunnelAttributionSelect,
    FunnelConversionWindowFilter,
    commonActionFilterProps,
} from './Selectors'

export function FunnelsMetricForm({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { experiment, isExperimentRunning, editingPrimaryMetricUuid, editingSecondaryMetricUuid } =
        useValues(experimentLogic)
    const { setFunnelsMetric } = useActions(experimentLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const metricUuid = isSecondary ? editingSecondaryMetricUuid : editingPrimaryMetricUuid

    if (!metricUuid) {
        return <></>
    }

    const currentMetric = metrics.find((m) => m.uuid === metricUuid) as ExperimentFunnelsQuery

    if (!currentMetric) {
        return <></>
    }

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
                        if (!currentMetric.uuid) {
                            return
                        }
                        setFunnelsMetric({
                            uuid: currentMetric.uuid,
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

                    if (!currentMetric.uuid) {
                        return
                    }
                    setFunnelsMetric({
                        uuid: currentMetric.uuid,
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
                        if (!currentMetric.uuid) {
                            return
                        }
                        setFunnelsMetric({
                            uuid: currentMetric.uuid,
                            funnelAggregateByHogQL: value,
                            isSecondary,
                        })
                    }}
                />
                <FunnelConversionWindowFilter
                    funnelWindowInterval={currentMetric.funnels_query?.funnelsFilter?.funnelWindowInterval}
                    funnelWindowIntervalUnit={currentMetric.funnels_query?.funnelsFilter?.funnelWindowIntervalUnit}
                    onFunnelWindowIntervalChange={(funnelWindowInterval) => {
                        if (!currentMetric.uuid) {
                            return
                        }
                        setFunnelsMetric({
                            uuid: currentMetric.uuid,
                            funnelWindowInterval: funnelWindowInterval,
                            isSecondary,
                        })
                    }}
                    onFunnelWindowIntervalUnitChange={(funnelWindowIntervalUnit) => {
                        if (!currentMetric.uuid) {
                            return
                        }
                        setFunnelsMetric({
                            uuid: currentMetric.uuid,
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
                        if (!currentMetric.uuid) {
                            return
                        }
                        const [breakdownAttributionType, breakdownAttributionValue] = (value || '').split('/')
                        setFunnelsMetric({
                            uuid: currentMetric.uuid,
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
                        if (!currentMetric.uuid) {
                            return
                        }
                        setFunnelsMetric({
                            uuid: currentMetric.uuid,
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
