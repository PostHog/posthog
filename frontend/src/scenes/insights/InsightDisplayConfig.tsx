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
import {
    FunnelDisplayLayoutPicker,
    FunnelDisplayLayoutPickerDataExploration,
} from './views/Funnels/FunnelDisplayLayoutPicker'
import { PathStepPicker, PathStepPickerDataExploration } from './views/Paths/PathStepPicker'
import { ReferencePicker as RetentionReferencePicker } from './filters/ReferencePicker'
import { Tooltip } from 'antd'
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

function ConfigFilter(props: PropsWithChildren<ReactNode>): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{props.children}</span>
}

export function InsightDisplayConfig({ filters, disableTable }: InsightDisplayConfigProps): JSX.Element {
    const isFunnels = isFunnelsFilter(filters)
    const isPaths = isPathsFilter(filters)
    const { featureFlags } = useValues(featureFlagLogic)

    const { isUsingDataExploration, insightProps } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2">
                {filters.insight && showDateFilter[filters.insight] && !disableTable && (
                    <ConfigFilter>
                        <span>Date range</span>
                        <InsightDateFilter
                            disabled={isFunnels && isFunnelEmpty(filters)}
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

                {isPaths && (
                    <ConfigFilter>
                        {isUsingDataExploration ? (
                            <PathStepPickerDataExploration insightProps={insightProps} />
                        ) : (
                            <PathStepPicker insightProps={insightProps} />
                        )}
                    </ConfigFilter>
                )}

                {showCompareFilter(filters) && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center space-x-4 flex-wrap my-2">
                {isFilterWithDisplay(filters) && (
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

                {isFunnels && filters.funnel_viz_type === FunnelVizType.Steps && (
                    <>
                        <ConfigFilter>
                            {isUsingDataExploration ? (
                                <FunnelDisplayLayoutPickerDataExploration />
                            ) : (
                                <FunnelDisplayLayoutPicker />
                            )}
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
