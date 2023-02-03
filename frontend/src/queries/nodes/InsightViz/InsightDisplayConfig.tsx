import { PropsWithChildren, ReactNode } from 'react'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'antd'
import { CalendarOutlined, InfoCircleOutlined } from '@ant-design/icons'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightDisplayConfigLogic } from './insightDisplayConfigLogic'

import { InsightType } from '~/types'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { RetentionDatePickerDataExploration } from 'scenes/insights/RetentionDatePicker'
import { RetentionReferencePickerDataExploration } from 'scenes/insights/filters/RetentionReferencePicker'
import { PathStepPickerDataExploration } from 'scenes/insights/views/Paths/PathStepPicker'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { ChartFilter } from 'lib/components/ChartFilter'
import { FunnelDisplayLayoutPickerDataExploration } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
// import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'

interface InsightDisplayConfigProps {
    disableTable: boolean
}

export function InsightDisplayConfig({ disableTable }: InsightDisplayConfigProps): JSX.Element {
    const { insightProps, filters } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)
    const { isTrends, supportsDisplay } = useValues(insightDataLogic(insightProps))
    const {
        showDateRange,
        disableDateRange,
        showCompare,
        showInterval,
        showSmoothing,
        showRetention,
        showPaths,
        showFunnelDisplayLayout,
        // showFunnelBins,
    } = useValues(insightDisplayConfigLogic(insightProps))

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2">
                {showDateRange && !disableTable && (
                    <ConfigFilter>
                        <span>Date range</span>
                        <InsightDateFilter
                            disabled={disableDateRange}
                            makeLabel={(key) => (
                                <>
                                    <CalendarOutlined /> {key}
                                    {key == 'All time' && (
                                        <Tooltip title="Only events dated after 2015 will be shown">
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
                        <span className="hide-lte-md">grouped </span>by
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

                {showFunnelDisplayLayout && (
                    <ConfigFilter>
                        <FunnelDisplayLayoutPickerDataExploration />
                    </ConfigFilter>
                )}
                {/* {showFunnelBins && (
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
