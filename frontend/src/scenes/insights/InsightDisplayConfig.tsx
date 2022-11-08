import { PropsWithChildren, ReactNode } from 'react'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { ChartDisplayType, FilterType, FunnelVizType, InsightType, ItemMode } from '~/types'
import { CalendarOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { InsightDateFilter } from './filters/InsightDateFilter'
import { RetentionDatePicker } from './RetentionDatePicker'
import { FunnelDisplayLayoutPicker } from './views/Funnels/FunnelDisplayLayoutPicker'
import { PathStepPicker } from './views/Paths/PathStepPicker'
import { ReferencePicker as RetentionReferencePicker } from './filters/ReferencePicker'
import { Tooltip } from 'antd'
import { FunnelBinsPicker } from './views/Funnels/FunnelBinsPicker'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import {
    isFunnelsFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/utils/cleanFilters'

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
    return !filter.display || !NON_TIME_SERIES_DISPLAY_TYPES.includes(filter.display)
}

const showChartFilter = function (filters: Partial<FilterType>): boolean {
    return isTrendsFilter(filters) || isStickinessFilter(filters)
}

const showDateFilter = {
    [`${InsightType.TRENDS}`]: true,
    [`${InsightType.STICKINESS}`]: true,
    [`${InsightType.LIFECYCLE}`]: true,
    [`${InsightType.FUNNELS}`]: true,
    [`${InsightType.RETENTION}`]: false,
    [`${InsightType.PATHS}`]: true,
}

const showComparePrevious = {
    [`${InsightType.TRENDS}`]: true,
    [`${InsightType.STICKINESS}`]: true,
    [`${InsightType.LIFECYCLE}`]: false,
    [`${InsightType.FUNNELS}`]: false,
    [`${InsightType.RETENTION}`]: false,
    [`${InsightType.PATHS}`]: false,
}

const isFunnelEmpty = (filters: FilterType): boolean => {
    return (!filters.actions && !filters.events) || (filters.actions?.length === 0 && filters.events?.length === 0)
}

function ConfigFilter(props: PropsWithChildren<ReactNode>): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{props.children}</span>
}

export function InsightDisplayConfig({ filters, disableTable }: InsightDisplayConfigProps): JSX.Element {
    const showFunnelBarOptions = isFunnelsFilter(filters)
    const showPathOptions = isPathsFilter(filters)
    const { featureFlags } = useValues(featureFlagLogic)

    const { setFilters } = useActions(insightLogic)

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2">
                {filters.insight && showDateFilter[filters.insight] && !disableTable && (
                    <ConfigFilter>
                        <span>Date range</span>
                        <InsightDateFilter
                            disabled={showFunnelBarOptions && isFunnelEmpty(filters)}
                            makeLabel={(key) => (
                                <>
                                    <CalendarOutlined /> {key}
                                    {key == 'All time' && (
                                        <Tooltip title={`Only events dated after 2015 will be shown`}>
                                            <InfoCircleOutlined className="info-indicator" />
                                        </Tooltip>
                                    )}
                                </>
                            )}
                        />
                    </ConfigFilter>
                )}

                {showIntervalFilter(filters) && (
                    <ConfigFilter>
                        <span>
                            <span className="hide-lte-md">grouped </span>by
                        </span>
                        <IntervalFilter view={filters.insight || InsightType.TRENDS} />
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

                {isRetentionFilter(filters) && (
                    <ConfigFilter>
                        <RetentionDatePicker />
                        <RetentionReferencePicker />
                    </ConfigFilter>
                )}

                {showPathOptions && (
                    <ConfigFilter>
                        <PathStepPicker />
                    </ConfigFilter>
                )}

                {filters.insight && showComparePrevious[filters.insight] && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center space-x-4 flex-wrap my-2">
                {showChartFilter(filters) && (
                    <>
                        {isTrendsFilter(filters) && (
                            <ConfigFilter>
                                <UnitPicker filters={filters} setFilters={setFilters} />
                            </ConfigFilter>
                        )}
                        <ConfigFilter>
                            <span>Chart type</span>
                            <ChartFilter filters={filters} />
                        </ConfigFilter>
                    </>
                )}

                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.Steps && (
                    <>
                        <ConfigFilter>
                            <FunnelDisplayLayoutPicker />
                        </ConfigFilter>
                    </>
                )}
                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.TimeToConvert && (
                    <ConfigFilter>
                        <FunnelBinsPicker />
                    </ConfigFilter>
                )}
            </div>
        </div>
    )
}
