import { useValues } from 'kea'
import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { TZIndicator } from 'lib/components/TimezoneAware'
import { ACTIONS_BAR_CHART_VALUE, ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_PIE_CHART, ACTIONS_TABLE } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import { DisplayType, FilterType } from '~/types'
import { ViewType } from '../insightLogic'
import { CalendarOutlined } from '@ant-design/icons'
import { InsightDateFilter } from '../InsightDateFilter'
import { RetentionDatePicker } from '../RetentionDatePicker'

interface InsightDisplayConfigProps {
    clearAnnotationsToCreate: () => void
    allFilters: FilterType
    activeView: ViewType
    annotationsToCreate: any[] // TODO: Annotate properly
}

export function InsightDisplayConfig({
    horizontalUI,
    ...props
}: InsightDisplayConfigProps & { horizontalUI: boolean }): JSX.Element {
    return horizontalUI ? (
        <HorizontalDefaultInsightDisplayConfig {...props} />
    ) : (
        <DefaultInsightDisplayConfig {...props} />
    )
}

const showIntervalFilter = function (activeView: ViewType, filter: FilterType): boolean {
    switch (activeView) {
        case ViewType.FUNNELS:
            return filter.display === ACTIONS_LINE_GRAPH_LINEAR
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

const showChartFilter = function (activeView: ViewType, featureFlags: Record<string, boolean>): boolean {
    switch (activeView) {
        case ViewType.TRENDS:
        case ViewType.STICKINESS:
        case ViewType.SESSIONS:
        case ViewType.RETENTION:
            return true
        case ViewType.FUNNELS:
            return featureFlags['funnel-trends-1269']
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

function DefaultInsightDisplayConfig({
    allFilters,
    activeView,
    clearAnnotationsToCreate,
    annotationsToCreate,
}: InsightDisplayConfigProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const dateFilterDisabled = activeView === ViewType.FUNNELS && isFunnelEmpty(allFilters)

    return (
        <div style={{ display: 'flex', alignItems: 'center' }}>
            <TZIndicator style={{ float: 'left' }} />
            <div style={{ width: '100%', textAlign: 'right' }}>
                {showIntervalFilter(activeView, allFilters) && <IntervalFilter view={activeView} />}
                {showChartFilter(activeView, featureFlags) && (
                    <ChartFilter
                        onChange={(display: DisplayType) => {
                            if (display === ACTIONS_TABLE || display === ACTIONS_PIE_CHART) {
                                clearAnnotationsToCreate()
                            }
                        }}
                        filters={allFilters}
                        disabled={allFilters.insight === ViewType.LIFECYCLE}
                    />
                )}

                {showDateFilter[activeView] && (
                    <InsightDateFilter defaultValue="Last 7 days" disabled={dateFilterDisabled} bordered={false} />
                )}

                {showComparePrevious[activeView] && <CompareFilter />}
                <SaveToDashboard
                    item={{
                        entity: {
                            filters: allFilters,
                            annotations: annotationsToCreate,
                        },
                    }}
                />
            </div>
        </div>
    )
}

function HorizontalDefaultInsightDisplayConfig({
    allFilters,
    activeView,
    clearAnnotationsToCreate,
}: InsightDisplayConfigProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const dateFilterDisabled = activeView === ViewType.FUNNELS && isFunnelEmpty(allFilters)

    return (
        <div className="display-config-inner">
            <span className="hide-lte-md">
                <TZIndicator style={{ float: 'left', fontSize: '0.75rem', marginRight: 16 }} placement="topRight" />
            </span>
            <div style={{ width: '100%', textAlign: 'right' }}>
                {showChartFilter(activeView, featureFlags) && (
                    <ChartFilter
                        onChange={(display: DisplayType) => {
                            if (display === ACTIONS_TABLE || display === ACTIONS_PIE_CHART) {
                                clearAnnotationsToCreate()
                            }
                        }}
                        filters={allFilters}
                        disabled={allFilters.insight === ViewType.LIFECYCLE}
                    />
                )}
                {showIntervalFilter(activeView, allFilters) && <IntervalFilter view={activeView} />}

                {activeView === ViewType.RETENTION && <RetentionDatePicker />}

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
