import React, { PropsWithChildren, ReactNode, useState } from 'react'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { FilterType, FunnelVizType, ItemMode, InsightType, ChartDisplayType } from '~/types'
import { CalendarOutlined } from '@ant-design/icons'
import { InsightDateFilter } from './filters/InsightDateFilter'
import { RetentionDatePicker } from './RetentionDatePicker'
import { FunnelDisplayLayoutPicker } from './views/Funnels/FunnelDisplayLayoutPicker'
import { PathStepPicker } from './views/Paths/PathStepPicker'
import { ReferencePicker as RetentionReferencePicker } from './filters/ReferencePicker'
import { Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { FunnelBinsPicker } from './views/Funnels/FunnelBinsPicker'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'
import { aggregationAxisFormatSelectOptions, axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { CurrencyPicker, isCurrency } from 'lib/components/CurrencyPicker/CurrencyPicker'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'

interface InsightDisplayConfigProps {
    filters: FilterType
    activeView: InsightType
    insightMode: ItemMode
    disableTable: boolean
}

const showIntervalFilter = function (activeView: InsightType, filter: FilterType): boolean {
    switch (activeView) {
        case InsightType.FUNNELS:
            return filter.funnel_viz_type === FunnelVizType.Trends
        case InsightType.RETENTION:
        case InsightType.PATHS:
            return false
        case InsightType.TRENDS:
        case InsightType.STICKINESS:
        case InsightType.LIFECYCLE:
        default:
            return !filter.display || !NON_TIME_SERIES_DISPLAY_TYPES.includes(filter.display)
    }
}

const showChartFilter = function (activeView: InsightType): boolean {
    switch (activeView) {
        case InsightType.TRENDS:
        case InsightType.STICKINESS:
            return true
        case InsightType.RETENTION:
        case InsightType.FUNNELS:
            return false
        case InsightType.LIFECYCLE:
        case InsightType.PATHS:
            return false
        default:
            return true // sometimes insights aren't set for trends
    }
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

export function InsightDisplayConfig({ filters, activeView, disableTable }: InsightDisplayConfigProps): JSX.Element {
    const showFunnelBarOptions = activeView === InsightType.FUNNELS
    const showPathOptions = activeView === InsightType.PATHS
    const { featureFlags } = useValues(featureFlagLogic)

    const { setFilters } = useActions(insightLogic)

    const [isVisible, setIsVisible] = useState(false)
    const [chosenThingy, setChosenThingy] = useState(filters.aggregation_axis_format)

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2">
                {showDateFilter[activeView] && !disableTable && (
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

                {showIntervalFilter(activeView, filters) && (
                    <ConfigFilter>
                        <span>
                            <span className="hide-lte-md">grouped </span>by
                        </span>
                        <IntervalFilter view={activeView} />
                    </ConfigFilter>
                )}

                {activeView === InsightType.TRENDS &&
                !filters.breakdown_type &&
                !filters.compare &&
                (!filters.display || filters.display === ChartDisplayType.ActionsLineGraph) &&
                featureFlags[FEATURE_FLAGS.SMOOTHING_INTERVAL] ? (
                    <ConfigFilter>
                        <SmoothingFilter />
                    </ConfigFilter>
                ) : null}

                {activeView === InsightType.RETENTION && (
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

                {showComparePrevious[activeView] && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center space-x-4 flex-wrap my-2">
                {showChartFilter(activeView) && (
                    <>
                        {activeView === InsightType.TRENDS && (
                            <ConfigFilter>
                                <span>{axisLabel(filters.display)}</span>
                                <LemonButtonWithPopup
                                    onClick={() => setIsVisible(!isVisible)}
                                    size={'small'}
                                    type={'secondary'}
                                    status="stealth"
                                    data-attr="chart-aggregation-axis-format"
                                    popup={{
                                        onClickOutside: close,
                                        maxContentWidth: false,
                                        visible: isVisible,
                                        className: 'UnitPopup',
                                        overlay: (
                                            <>
                                                {aggregationAxisFormatSelectOptions.map(({ value, label }, index) => (
                                                    <LemonButton
                                                        key={index}
                                                        onClick={() => {
                                                            console.log(value)
                                                            setChosenThingy(value)
                                                            setIsVisible(false)
                                                            setFilters({ ...filters, aggregation_axis_format: value })
                                                        }}
                                                        status="stealth"
                                                        active={value === chosenThingy}
                                                        fullWidth
                                                    >
                                                        {label}
                                                    </LemonButton>
                                                ))}
                                                <LemonDivider />
                                                <h5>Currency</h5>
                                                <CurrencyPicker
                                                    value={isCurrency(chosenThingy) ? [chosenThingy as string] : []}
                                                    onChange={(currency) => {
                                                        setChosenThingy(currency)
                                                        setIsVisible(false)
                                                        setFilters({ ...filters, aggregation_axis_format: currency })
                                                    }}
                                                />
                                            </>
                                        ),
                                        placement: 'bottom-start',
                                        actionable: true,
                                        closeOnClickInside: false,
                                    }}
                                >
                                    {filters.aggregation_axis_format || 'None'}
                                </LemonButtonWithPopup>
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
