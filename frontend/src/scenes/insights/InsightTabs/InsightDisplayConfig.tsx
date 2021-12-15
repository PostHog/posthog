import React from 'react'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { ACTIONS_BAR_CHART_VALUE, ACTIONS_PIE_CHART, ACTIONS_TABLE, FEATURE_FLAGS } from 'lib/constants'
import { ChartDisplayType, FilterType, FunnelVizType, ItemMode, InsightType } from '~/types'
import { CalendarOutlined } from '@ant-design/icons'
import { InsightDateFilter } from '../InsightDateFilter'
import { RetentionDatePicker } from '../RetentionDatePicker'
import { FunnelStepReferencePicker } from './FunnelTab/FunnelStepReferencePicker'
import { FunnelDisplayLayoutPicker } from './FunnelTab/FunnelDisplayLayoutPicker'
import { FunnelBinsPicker } from 'scenes/insights/InsightTabs/FunnelTab/FunnelBinsPicker'
import { PathStepPicker } from './PathTab/PathStepPicker'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

interface InsightDisplayConfigProps {
    clearAnnotationsToCreate: () => void
    filters: FilterType
    activeView: InsightType
    insightMode: ItemMode
    disableTable: boolean
    annotationsToCreate: Record<string, any>[] // TODO: Annotate properly
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
        case InsightType.SESSIONS:
        default:
            return ![ACTIONS_PIE_CHART, ACTIONS_TABLE, ACTIONS_BAR_CHART_VALUE].includes(filter.display || '') // sometimes insights aren't set for trends
    }
}

const showChartFilter = function (activeView: InsightType): boolean {
    switch (activeView) {
        case InsightType.TRENDS:
        case InsightType.STICKINESS:
        case InsightType.SESSIONS:
        case InsightType.RETENTION:
            return true
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
    [`${InsightType.SESSIONS}`]: true,
    [`${InsightType.FUNNELS}`]: true,
    [`${InsightType.RETENTION}`]: false,
    [`${InsightType.PATHS}`]: true,
}

const showComparePrevious = {
    [`${InsightType.TRENDS}`]: true,
    [`${InsightType.STICKINESS}`]: true,
    [`${InsightType.LIFECYCLE}`]: false,
    [`${InsightType.SESSIONS}`]: true,
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
    clearAnnotationsToCreate,
    disableTable,
}: InsightDisplayConfigProps): JSX.Element {
    const showFunnelBarOptions = activeView === InsightType.FUNNELS
    const showPathOptions = activeView === InsightType.PATHS
    const dateFilterDisabled = showFunnelBarOptions && isFunnelEmpty(filters)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="display-config-inner">
            <div className="display-config-inner-row">
                {showDateFilter[activeView] && !disableTable && (
                    <span className="filter">
                        <span className="head-title-item">Date range</span>
                        <InsightDateFilter
                            disabled={dateFilterDisabled}
                            bordered
                            makeLabel={(key) => (
                                <>
                                    <CalendarOutlined /> {key}
                                </>
                            )}
                            isDateFormatted
                        />
                    </span>
                )}
                {showIntervalFilter(activeView, filters) && (
                    <span className="filter">
                        <span className="head-title-item">
                            <span className="hide-lte-md">grouped </span>by
                        </span>
                        <IntervalFilter view={activeView} />
                    </span>
                )}

                {activeView === InsightType.RETENTION && <RetentionDatePicker />}

                {showPathOptions && (
                    <span className="filter">
                        <PathStepPicker />
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
                            onChange={(display: ChartDisplayType | FunnelVizType) => {
                                if (display === ACTIONS_TABLE || display === ACTIONS_PIE_CHART) {
                                    clearAnnotationsToCreate()
                                }
                            }}
                            filters={filters}
                            disabled={filters.insight === InsightType.LIFECYCLE}
                        />
                    </span>
                )}
                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.Steps && (
                    <>
                        <span className="filter">
                            <FunnelDisplayLayoutPicker />
                        </span>
                        {!featureFlags[FEATURE_FLAGS.FUNNEL_SIMPLE_MODE] && (
                            <span className="filter">
                                <FunnelStepReferencePicker bordered />
                            </span>
                        )}
                    </>
                )}
                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.TimeToConvert && (
                    <span className="filter">
                        <FunnelBinsPicker />
                    </span>
                )}
            </div>
        </div>
    )
}
