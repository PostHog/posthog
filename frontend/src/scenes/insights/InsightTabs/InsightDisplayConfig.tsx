import React from 'react'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { ACTIONS_LINE_GRAPH_LINEAR } from 'lib/constants'
import { FilterType, FunnelVizType, ItemMode, InsightType, ChartDisplayType } from '~/types'
import { CalendarOutlined } from '@ant-design/icons'
import { InsightDateFilter } from '../InsightDateFilter'
import { RetentionDatePicker } from '../RetentionDatePicker'
import { FunnelDisplayLayoutPicker } from './FunnelTab/FunnelDisplayLayoutPicker'
import { PathStepPicker } from './PathTab/PathStepPicker'
import { ReferencePicker as RetentionReferencePicker } from './RetentionTab/ReferencePicker'
import { Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { FunnelBinsPicker } from './FunnelTab/FunnelBinsPicker'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { apiValueToMathType, mathsLogic } from 'scenes/trends/mathsLogic'
import { LocalFilter, toLocalFilters } from '../ActionFilter/entityFilterLogic'

interface InsightDisplayConfigProps {
    filters: FilterType
    activeView: InsightType
    insightMode: ItemMode
    disableTable: boolean
    disabled?: boolean
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
            return (
                !filter.display ||
                ![
                    ChartDisplayType.ActionsPie,
                    ChartDisplayType.ActionsTable,
                    ChartDisplayType.ActionsBarValue,
                    ChartDisplayType.WorldMap,
                ].includes(filter.display)
            )
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

export function InsightDisplayConfig({
    filters,
    activeView,
    disableTable,
    disabled,
}: InsightDisplayConfigProps): JSX.Element {
    const showFunnelBarOptions = activeView === InsightType.FUNNELS
    const showPathOptions = activeView === InsightType.PATHS
    const { featureFlags } = useValues(featureFlagLogic)
    const { mathDefinitions } = useValues(mathsLogic)

    let showLive = false
    if (activeView === InsightType.TRENDS && filters.display === ChartDisplayType.WorldMap) {
        const firstSeries: LocalFilter | undefined = toLocalFilters(filters)[0]
        // Live mode is only intended for user activity, not event counts,
        // so show Live option for World Map only if the single series is actor-based
        if (
            firstSeries &&
            mathDefinitions[apiValueToMathType(firstSeries.math, firstSeries.math_group_type_index)]?.actor
        ) {
            showLive = true
        }
    }

    return (
        <div className="display-config-inner">
            <div className="display-config-inner-row">
                {showDateFilter[activeView] && !disableTable && (
                    <span className="filter">
                        <span className="head-title-item">Date range</span>
                        <InsightDateFilter
                            defaultValue="Last 7 days"
                            showLive={showLive}
                            disabled={disabled || (showFunnelBarOptions && isFunnelEmpty(filters))}
                            bordered
                            makeLabel={(key) => (
                                <>
                                    {key === 'Live' ? <div className="live-indicator" /> : <CalendarOutlined />} {key}
                                    {key === 'All time' && (
                                        <Tooltip title={`Only events dated after 2015 will be shown`}>
                                            <InfoCircleOutlined className="info-indicator" />
                                        </Tooltip>
                                    )}
                                </>
                            )}
                        />
                    </span>
                )}

                {showIntervalFilter(activeView, filters) && (
                    <span className="filter">
                        <span className="head-title-item">
                            <span className="hide-lte-md">grouped </span>by
                        </span>
                        <IntervalFilter view={activeView} disabled={disabled} />
                    </span>
                )}

                {activeView === InsightType.TRENDS &&
                !filters.breakdown_type &&
                !filters.compare &&
                (!filters.display || filters.display === ACTIONS_LINE_GRAPH_LINEAR) &&
                featureFlags[FEATURE_FLAGS.SMOOTHING_INTERVAL] ? (
                    <SmoothingFilter />
                ) : null}

                {activeView === InsightType.RETENTION && (
                    <>
                        <RetentionDatePicker disabled={disabled} />
                        <RetentionReferencePicker disabled={disabled} />
                    </>
                )}

                {showPathOptions && (
                    <span className="filter">
                        <PathStepPicker disabled={disabled} />
                    </span>
                )}

                {showComparePrevious[activeView] && (
                    <span className="filter">
                        <CompareFilter />
                    </span>
                )}
            </div>
            <div className="display-config-inner-row">
                {showChartFilter(activeView) && (
                    <span className="filter">
                        <span className="head-title-item">Chart type</span>
                        <ChartFilter
                            filters={filters}
                            disabled={disabled || filters.insight === InsightType.LIFECYCLE}
                        />
                    </span>
                )}
                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.Steps && (
                    <>
                        <span className="filter">
                            <FunnelDisplayLayoutPicker disabled={disabled} />
                        </span>
                    </>
                )}
                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.TimeToConvert && (
                    <span className="filter">
                        <FunnelBinsPicker disabled={disabled} />
                    </span>
                )}
            </div>
        </div>
    )
}
