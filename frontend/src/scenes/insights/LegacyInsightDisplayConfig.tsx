import { PropsWithChildren, ReactNode } from 'react'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { ChartDisplayType, FilterType, InsightType, ItemMode, TrendsFilterType } from '~/types'

import { InsightDateFilter } from './filters/InsightDateFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { isFilterWithDisplay, isTrendsFilter, isAreaChartDisplay } from 'scenes/insights/sharedUtils'

interface InsightDisplayConfigProps {
    filters: FilterType
    activeView: InsightType
    insightMode: ItemMode
    disableTable: boolean
}

const showIntervalFilter = function (filter: Partial<FilterType>): boolean {
    const display = (filter as TrendsFilterType).display
    return !display || !NON_TIME_SERIES_DISPLAY_TYPES.includes(display)
}

const showCompareFilter = function (filters: Partial<FilterType>): boolean {
    return !isAreaChartDisplay(filters)
}

function ConfigFilter(props: PropsWithChildren<ReactNode>): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{props.children}</span>
}

export function LegacyInsightDisplayConfig({ filters, disableTable }: InsightDisplayConfigProps): JSX.Element {
    if (!isTrendsFilter(filters)) {
        // This legacy component is being removed, don't use it
        throw new Error('Unsupported insight type')
    }

    const { featureFlags } = useValues(featureFlagLogic)

    const { setFilters } = useActions(insightLogic)

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2 gap-y-2">
                {filters.insight && !disableTable && (
                    <ConfigFilter>
                        <InsightDateFilter disabled={false} />
                    </ConfigFilter>
                )}

                {showIntervalFilter(filters) && (
                    <ConfigFilter>
                        <IntervalFilter />
                    </ConfigFilter>
                )}

                {!filters.breakdown_type &&
                !filters.compare &&
                (!filters.display || filters.display === ChartDisplayType.ActionsLineGraph) &&
                featureFlags[FEATURE_FLAGS.SMOOTHING_INTERVAL] ? (
                    <ConfigFilter>
                        <SmoothingFilter />
                    </ConfigFilter>
                ) : null}

                {showCompareFilter(filters) && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center space-x-4 flex-wrap my-2 grow justify-end">
                {isFilterWithDisplay(filters) && (
                    <>
                        <ConfigFilter>
                            <UnitPicker filters={filters} setFilters={setFilters} />
                        </ConfigFilter>

                        <ConfigFilter>
                            <ChartFilter filters={filters} />
                        </ConfigFilter>
                    </>
                )}
            </div>
        </div>
    )
}
