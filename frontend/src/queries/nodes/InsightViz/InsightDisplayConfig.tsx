import { PropsWithChildren, ReactNode } from 'react'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'antd'

import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { ChartDisplayType, FilterType, InsightType, ItemMode } from '~/types'
import { CalendarOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { FunnelDisplayLayoutPickerDataExploration } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { PathStepPickerDataExploration } from 'scenes/insights/views/Paths/PathStepPicker'
import { RetentionDatePickerDataExploration } from 'scenes/insights/RetentionDatePicker'
import { RetentionReferencePickerDataExploration } from 'scenes/insights/filters/RetentionReferencePicker'
// import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

interface InsightDisplayConfigProps {
    filters: FilterType
    activeView: InsightType
    insightMode: ItemMode
    disableTable: boolean
}

export function InsightDisplayConfig({ filters, disableTable }: InsightDisplayConfigProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { insightProps } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)
    const {
        isTrends,
        isFunnels,
        isRetention,
        isPaths,
        isStickiness,
        isLifecycle,
        supportsDisplay,
        display,
        breakdown,
        trendsFilter,
    } = useValues(insightDataLogic(insightProps))
    const {
        isEmptyFunnel,
        isStepsFunnel,
        // isTimeToConvertFunnel,
        isTrendsFunnel,
    } = useValues(funnelDataLogic(insightProps))

    const showDateRange = filters.insight && !isRetention && !disableTable

    const showCompare = (isTrends && display !== ChartDisplayType.ActionsAreaGraph) || isStickiness
    const showInterval =
        isTrendsFunnel ||
        isLifecycle ||
        ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display)))
    const showSmoothing =
        isTrends &&
        !breakdown?.breakdown_type &&
        !trendsFilter?.compare &&
        (!display || display === ChartDisplayType.ActionsLineGraph) &&
        featureFlags[FEATURE_FLAGS.SMOOTHING_INTERVAL]
    const showRetention = !!isRetention
    const showPaths = !!isPaths

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2">
                {showDateRange && (
                    <ConfigFilter>
                        <span>Date range</span>
                        <InsightDateFilter
                            disabled={isEmptyFunnel}
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

                {showInterval && (
                    <ConfigFilter>
                        <span>
                            <span className="hide-lte-md">grouped </span>by
                        </span>
                        <IntervalFilter view={filters.insight || InsightType.TRENDS} />
                    </ConfigFilter>
                )}

                {showSmoothing && (
                    <ConfigFilter>
                        <SmoothingFilter />
                    </ConfigFilter>
                )}

                {showRetention && (
                    <ConfigFilter>
                        <RetentionDatePickerDataExploration />
                        <RetentionReferencePickerDataExploration />
                    </ConfigFilter>
                )}

                {showPaths && (
                    <ConfigFilter>
                        <PathStepPickerDataExploration insightProps={insightProps} />
                    </ConfigFilter>
                )}

                {showCompare && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center space-x-4 flex-wrap my-2">
                {supportsDisplay && (
                    <>
                        {isTrends && (
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

                {isStepsFunnel && (
                    <ConfigFilter>
                        <FunnelDisplayLayoutPickerDataExploration />
                    </ConfigFilter>
                )}
                {/* {isTimeToConvertFunnel && (
                    <ConfigFilter>
                        <FunnelBinsPicker />
                    </ConfigFilter>
                )} */}
            </div>
        </div>
    )
}

function ConfigFilter(props: PropsWithChildren<ReactNode>): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{props.children}</span>
}
