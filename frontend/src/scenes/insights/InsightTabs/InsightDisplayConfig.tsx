import React from 'react'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { TZIndicator } from 'lib/components/TimezoneAware'
import { ACTIONS_BAR_CHART_VALUE, ACTIONS_PIE_CHART, ACTIONS_TABLE, FEATURE_FLAGS } from 'lib/constants'
import { ChartDisplayType, FilterType, FunnelVizType, ItemMode, ViewType } from '~/types'
import { CalendarOutlined } from '@ant-design/icons'
import { InsightDateFilter } from '../InsightDateFilter'
import { RetentionDatePicker } from '../RetentionDatePicker'
import { FunnelStepReferencePicker } from './FunnelTab/FunnelStepReferencePicker'
import { FunnelDisplayLayoutPicker } from './FunnelTab/FunnelDisplayLayoutPicker'
import { FunnelBinsPicker } from 'scenes/insights/InsightTabs/FunnelTab/FunnelBinsPicker'
import { PathStepPicker } from './PathTab/PathStepPicker'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
interface InsightDisplayConfigProps {
    clearAnnotationsToCreate: () => void
    filters: FilterType
    activeView: ViewType
    insightMode: ItemMode
    annotationsToCreate: Record<string, any>[] // TODO: Annotate properly
}

const showIntervalFilter = function (activeView: ViewType, filter: FilterType): boolean {
    switch (activeView) {
        case ViewType.FUNNELS:
            return filter.funnel_viz_type === FunnelVizType.Trends
        case ViewType.RETENTION:
        case ViewType.PATHS:
            return false
        case ViewType.TRENDS:
        case ViewType.STICKINESS:
        case ViewType.LIFECYCLE:
        case ViewType.SESSIONS:
        default:
            return ![ACTIONS_PIE_CHART, ACTIONS_TABLE, ACTIONS_BAR_CHART_VALUE].includes(filter.display || '') // sometimes insights aren't set for trends
    }
}

const showChartFilter = function (activeView: ViewType): boolean {
    switch (activeView) {
        case ViewType.TRENDS:
        case ViewType.STICKINESS:
        case ViewType.SESSIONS:
        case ViewType.RETENTION:
            return true
        case ViewType.FUNNELS:
            return false
        case ViewType.LIFECYCLE:
        case ViewType.PATHS:
            return false
        default:
            return true // sometimes insights aren't set for trends
    }
}

const showDateFilter = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.STICKINESS}`]: true,
    [`${ViewType.LIFECYCLE}`]: true,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: true,
    [`${ViewType.RETENTION}`]: false,
    [`${ViewType.PATHS}`]: true,
}

const showComparePrevious = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.STICKINESS}`]: true,
    [`${ViewType.LIFECYCLE}`]: false,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: false,
    [`${ViewType.RETENTION}`]: false,
    [`${ViewType.PATHS}`]: false,
}

const isFunnelEmpty = (filters: FilterType): boolean => {
    return (!filters.actions && !filters.events) || (filters.actions?.length === 0 && filters.events?.length === 0)
}

export function InsightDisplayConfig({
    filters,
    insightMode,
    activeView,
    clearAnnotationsToCreate,
}: InsightDisplayConfigProps): JSX.Element {
    const showFunnelBarOptions = activeView === ViewType.FUNNELS
    const showPathOptions = activeView === ViewType.PATHS

    const { featureFlags } = useValues(featureFlagLogic)
    const dateFilterDisabled =
        (showFunnelBarOptions && isFunnelEmpty(filters)) ||
        (!!featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS] && insightMode === ItemMode.View)

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
                        disabled={filters.insight === ViewType.LIFECYCLE}
                    />
                )}
                {showIntervalFilter(activeView, filters) && <IntervalFilter view={activeView} />}

                {activeView === ViewType.RETENTION && <RetentionDatePicker />}

                {showFunnelBarOptions && filters.funnel_viz_type === FunnelVizType.Steps && (
                    <>
                        <FunnelDisplayLayoutPicker />
                        <FunnelStepReferencePicker />
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
