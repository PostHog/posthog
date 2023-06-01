import { PropsWithChildren, ReactNode } from 'react'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { NON_VALUES_ON_SERIES_DISPLAY_TYPES, FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { ChartDisplayType, FilterType, FunnelVizType, InsightType, ItemMode, TrendsFilterType } from '~/types'

import { InsightDateFilter } from './filters/InsightDateFilter'
import { FunnelDisplayLayoutPicker } from './views/Funnels/FunnelDisplayLayoutPicker'
import { PathStepPicker } from './views/Paths/PathStepPicker'
import { FunnelBinsPicker } from './views/Funnels/FunnelBinsPicker'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import {
    isFilterWithDisplay,
    isFunnelsFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
    isAreaChartDisplay,
    isLifecycleFilter,
} from 'scenes/insights/sharedUtils'
import { ValueOnSeriesFilter } from './EditorFilters/ValueOnSeriesFilter'

interface InsightDisplayConfigProps {
    filters: FilterType
    activeView: InsightType
    insightMode: ItemMode
    disableTable: boolean
}

const showIntervalFilter = function (filter: Partial<FilterType>): boolean {
    if (isFunnelsFilter(filter)) {
        return filter.funnel_viz_type === FunnelVizType.Trends
    }
    if (isRetentionFilter(filter) || isPathsFilter(filter)) {
        return false
    }

    if (isLifecycleFilter(filter)) {
        return true
    }

    return (
        (isTrendsFilter(filter) || isStickinessFilter(filter)) &&
        (!filter.display || !NON_TIME_SERIES_DISPLAY_TYPES.includes(filter.display))
    )
}

const showDateFilter = {
    [`${InsightType.TRENDS}`]: true,
    [`${InsightType.STICKINESS}`]: true,
    [`${InsightType.LIFECYCLE}`]: true,
    [`${InsightType.FUNNELS}`]: true,
    [`${InsightType.RETENTION}`]: false,
    [`${InsightType.PATHS}`]: true,
}

const showCompareFilter = function (filters: Partial<FilterType>): boolean {
    if (isTrendsFilter(filters)) {
        return !isAreaChartDisplay(filters)
    }

    if (isStickinessFilter(filters)) {
        return true
    }

    return false
}

const isFunnelEmpty = (filters: FilterType): boolean => {
    return (!filters.actions && !filters.events) || (filters.actions?.length === 0 && filters.events?.length === 0)
}

const showValueOnSeriesFilter = (filters: FilterType): boolean => {
    if (isTrendsFilter(filters) || isStickinessFilter(filters)) {
        return !NON_VALUES_ON_SERIES_DISPLAY_TYPES.includes(filters.display || ChartDisplayType.ActionsLineGraph)
    } else if (isLifecycleFilter(filters)) {
        return true
    } else {
        return false
    }
}

function ConfigFilter(props: PropsWithChildren<ReactNode>): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{props.children}</span>
}

export function LegacyInsightDisplayConfig({ filters, disableTable }: InsightDisplayConfigProps): JSX.Element {
    if (!isFunnelsFilter(filters) && !isTrendsFilter(filters)) {
        // The legacy InsightContainer should only be used in Experiments,
        // where we only have funnel and trend insights, allowing us already
        // to gradually remove the other insight types here
        throw new Error('Unsupported insight type')
    }

    const isFunnels = isFunnelsFilter(filters)
    const isPaths = isPathsFilter(filters)
    const { featureFlags } = useValues(featureFlagLogic)

    const { insightProps } = useValues(insightLogic)
    const { setFilters, setFiltersMerge } = useActions(insightLogic)

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2 gap-y-2">
                {filters.insight && showDateFilter[filters.insight] && !disableTable && (
                    <ConfigFilter>
                        <InsightDateFilter disabled={isFunnels && isFunnelEmpty(filters)} />
                    </ConfigFilter>
                )}

                {showIntervalFilter(filters) && (
                    <ConfigFilter>
                        <IntervalFilter />
                    </ConfigFilter>
                )}

                {isTrendsFilter(filters) &&
                !filters.breakdown_type &&
                !filters.compare &&
                (!filters.display || filters.display === ChartDisplayType.ActionsLineGraph) &&
                featureFlags[FEATURE_FLAGS.SMOOTHING_INTERVAL] ? (
                    <ConfigFilter>
                        <SmoothingFilter />
                    </ConfigFilter>
                ) : null}

                {isPaths && (
                    <ConfigFilter>
                        <PathStepPicker insightProps={insightProps} />
                    </ConfigFilter>
                )}

                {showCompareFilter(filters) && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}

                {showValueOnSeriesFilter(filters) && (
                    <ConfigFilter>
                        <ValueOnSeriesFilter
                            checked={
                                !!(
                                    ((isTrendsFilter(filters) ||
                                        isStickinessFilter(filters) ||
                                        isLifecycleFilter(filters)) &&
                                        (filters as TrendsFilterType).show_values_on_series) ||
                                    // pie charts have value checked by default
                                    (isTrendsFilter(filters) &&
                                        filters.display === ChartDisplayType.ActionsPie &&
                                        filters.show_values_on_series === undefined)
                                )
                            }
                            onChange={(checked) => {
                                setFiltersMerge({ show_values_on_series: checked } as TrendsFilterType)
                            }}
                        />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center space-x-4 flex-wrap my-2 grow justify-end">
                {isFilterWithDisplay(filters) && (
                    <>
                        {isTrendsFilter(filters) && (
                            <ConfigFilter>
                                <UnitPicker filters={filters} setFilters={setFilters} />
                            </ConfigFilter>
                        )}
                        <ConfigFilter>
                            <ChartFilter filters={filters} />
                        </ConfigFilter>
                    </>
                )}

                {isFunnels && filters.funnel_viz_type === FunnelVizType.Steps && (
                    <>
                        <ConfigFilter>
                            <FunnelDisplayLayoutPicker />
                        </ConfigFilter>
                    </>
                )}
                {isFunnels && filters.funnel_viz_type === FunnelVizType.TimeToConvert && (
                    <ConfigFilter>
                        <FunnelBinsPicker />
                    </ConfigFilter>
                )}
            </div>
        </div>
    )
}
