import React from 'react'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { TZIndicator } from 'lib/components/TimezoneAware'
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
}: InsightDisplayConfigProps): JSX.Element {
    const showFunnelBarOptions = activeView === InsightType.FUNNELS
    const showPathOptions = activeView === InsightType.PATHS
    const dateFilterDisabled = showFunnelBarOptions && isFunnelEmpty(filters)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="display-config-inner">
            <span className="hide-lte-md">
                <TZIndicator style={{ float: 'left', fontSize: '0.75rem', marginRight: 16 }} placement="topRight" />
            </span>
            <div style={{ width: '100%', textAlign: 'right' }}>
                {showChartFilter(activeView) && (
                    <ChartFilter
                        onChange={(display: ChartDisplayType | FunnelVizType) => {
                            if (display === ACTIONS_TABLE || display === ACTIONS_PIE_CHART) {
                                clearAnnotationsToCreate()
                            }
                        }}
                        filters={filters}
                        disabled={filters.insight === InsightType.LIFECYCLE}
                    />
                )}
                {showIntervalFilter(activeView, filters) && <IntervalFilter view={activeView} />}

                {activeView === InsightType.RETENTION && <RetentionDatePicker />}

                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.Steps && (
                    <>
                        <FunnelDisplayLayoutPicker />
                        {!featureFlags[FEATURE_FLAGS.FUNNEL_SIMPLE_MODE] && <FunnelStepReferencePicker />}
                    </>
                )}

                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.TimeToConvert && (
                    <>
                        <FunnelBinsPicker />
                    </>
                )}

                {showPathOptions && (
                    <>
                        <PathStepPicker />
                    </>
                )}

                {showDateFilter[activeView] && (
                    <>
                        <InsightDateFilter
                            defaultValue="Last 7 days"
                            disabled={dateFilterDisabled}
                            bordered={false}
                            makeLabel={(key) => (
                                <>
                                    <CalendarOutlined /> {key}
                                </>
                            )}
                        />
                    </>
                )}

                {showComparePrevious[activeView] && <CompareFilter />}
            </div>
        </div>
    )
}
