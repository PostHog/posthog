import React, { useState } from 'react'
import { useActions, useValues } from 'kea'

import { Card, Loading } from 'lib/utils'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { DateFilter } from 'lib/components/DateFilter'

import { ActionsPie } from './ActionsPie'
import { ActionsTable } from './ActionsTable'
import { ActionsLineGraph } from './ActionsLineGraph'
import { PeopleModal } from './PeopleModal'

import { ChartFilter } from 'lib/components/ChartFilter'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic'
import { Tabs, Row, Col } from 'antd'
import {
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    LINEAR_CHART_LABEL,
    CUMULATIVE_CHART_LABEL,
    TABLE_LABEL,
    PIE_CHART_LABEL,
    STEPS_LABEL,
    TRENDS_LABEL,
    ACTIONS_TABLE,
    ACTIONS_PIE_CHART,
    RETENTION_TABLE,
    PATHS_VIZ,
    FUNNEL_STEPS,
    FUNNEL_TRENDS,
} from 'lib/constants'
import { hot } from 'react-hot-loader/root'
import { annotationsLogic } from '~/lib/components/Annotations'
import { router } from 'kea-router'

import { RetentionTable } from 'scenes/retention/RetentionTable'

import { Paths } from 'scenes/paths/Paths'

import { insightFilters } from './insightFilters'
import { FunnelSteps, FunnelLineGraph } from 'scenes/funnels/FunnelViz'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { People } from 'scenes/funnels/People'
import { insightLogic, ViewType } from './insightLogic'
import { trendsLogic } from './trendsLogic'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'

const { TabPane } = Tabs

const displayMap = {
    [ACTIONS_LINE_GRAPH_LINEAR]: LINEAR_CHART_LABEL,
    [ACTIONS_LINE_GRAPH_CUMULATIVE]: CUMULATIVE_CHART_LABEL,
    [ACTIONS_TABLE]: TABLE_LABEL,
    [ACTIONS_PIE_CHART]: PIE_CHART_LABEL,
    [FUNNEL_STEPS]: STEPS_LABEL,
    [FUNNEL_TRENDS]: TRENDS_LABEL,
}

const showChartFilter = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: true,
    [`${ViewType.RETENTION}`]: false,
    [`${ViewType.PATHS}`]: false,
}

const showDateFilter = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: true,
    [`${ViewType.RETENTION}`]: false,
    [`${ViewType.PATHS}`]: true,
}

const showComparePrevious = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: false,
    [`${ViewType.RETENTION}`]: false,
    [`${ViewType.PATHS}`]: false,
}

const disableSaveToDashboard = {
    [`${ViewType.TRENDS}`]: false,
    [`${ViewType.SESSIONS}`]: false,
    [`${ViewType.FUNNELS}`]: false,
    [`${ViewType.RETENTION}`]: true,
    [`${ViewType.PATHS}`]: true,
}

function shouldShowIntervalFilter(viewType: string, chartDisplay?: string): boolean {
    if ([ViewType.TRENDS, ViewType.SESSIONS].includes(viewType)) return true
    if (viewType === ViewType.FUNNELS && chartDisplay === 'FunnelTrends') return true
    return false
}

function determineInsightType(activeView: string, display?: string): string | null {
    if (activeView === ViewType.TRENDS || activeView === ViewType.SESSIONS) {
        return display || ACTIONS_LINE_GRAPH_LINEAR
    } else if (activeView === ViewType.FUNNELS) {
        return FUNNEL_STEPS
    } else if (activeView === ViewType.RETENTION) {
        return RETENTION_TABLE
    } else if (activeView === ViewType.PATHS) {
        return PATHS_VIZ
    } else {
        return null
    }
}

function TrendInsight({ view }): JSX.Element {
    const { filters, loading, showingPeople } = useValues(trendsLogic({ dashboardItemId: null, view, filters: null }))

    return (
        <>
            {(filters.actions || filters.events || filters.session) && (
                <div
                    style={{
                        minHeight: '70vh',
                        position: 'relative',
                    }}
                >
                    {loading && <Loading />}
                    {(!filters.display ||
                        filters.display === ACTIONS_LINE_GRAPH_LINEAR ||
                        filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE) && <ActionsLineGraph view={view} />}
                    {filters.display === ACTIONS_TABLE && <ActionsTable filters={filters} view={view} />}
                    {filters.display === ACTIONS_PIE_CHART && <ActionsPie filters={filters} view={view} />}
                </div>
            )}
            <PeopleModal visible={showingPeople} view={view} />
        </>
    )
}

function FunnelInsight(): JSX.Element {
    const { funnel, funnelLoading, stepsWithCount, stepsWithCountLoading, trends, trendsLoading } = useValues(
        funnelLogic({ id: null })
    )
    const { chartFilterFunnels } = useValues(chartFilterLogic)
    if (!funnel && funnelLoading) return <Loading />
    let content: JSX.Element
    if (stepsWithCountLoading || trendsLoading) {
        content = <Loading />
    } else if ((stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1) || trends?.length) {
        switch (chartFilterFunnels) {
            case FUNNEL_STEPS:
                content = <FunnelSteps funnel={{ steps: stepsWithCount }} />
                break
            case FUNNEL_TRENDS:
                content = <FunnelLineGraph funnel={{ ...funnel, trends }} />
                break
            default:
                content = <h3>Unknown funnel visualization type: {chartFilterFunnels}.</h3>
                break
        }
    } else {
        content = (
            <div
                style={{
                    textAlign: 'center',
                }}
            >
                <h3>Describe your funnel and click "Save funnel" to create a funnel visualization.</h3>
            </div>
        )
    }
    return <div style={{ height: 300, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>{content}</div>
}

function FunnelPeople(): JSX.Element {
    const { funnel } = useValues(funnelLogic({ id: null }))
    return (
        funnel.id && (
            <div className="funnel">
                <People />
            </div>
        )
    )
}

const insightGraphs: { [viewType: string]: JSX.Element } = {
    [ViewType.TRENDS]: <TrendInsight view={ViewType.TRENDS}></TrendInsight>,
    [ViewType.SESSIONS]: <TrendInsight view={ViewType.SESSIONS}></TrendInsight>,
    [ViewType.FUNNELS]: <FunnelInsight></FunnelInsight>,
    [ViewType.RETENTION]: <RetentionTable />,
    [ViewType.PATHS]: <Paths />,
}

export const Insights = hot(function () {
    const [{ fromItem }] = useState(router.values.hashParams)
    const { clearAnnotationsToCreate } = useActions(annotationsLogic({ pageKey: fromItem }))
    const { annotationsToCreate } = useValues(annotationsLogic({ pageKey: fromItem }))

    const { activeView, allFilters } = useValues(insightLogic)
    const { setActiveView, resetDisplayMode } = useActions(insightLogic)

    return (
        <div className="actions-graph">
            <h1 className="page-header">Insights</h1>
            <Tabs
                size="large"
                activeKey={activeView}
                style={{
                    overflow: 'visible',
                }}
                onChange={(key: string) => {
                    setActiveView(key)
                    resetDisplayMode()
                }}
                animated={false}
            >
                <TabPane
                    tab={<span data-attr="insight-trends-tab">Trends</span>}
                    key={ViewType.TRENDS}
                    data-attr="insight-trend-tab"
                />
                <TabPane
                    tab={<span data-attr="insight-sessions-tab">Sessions</span>}
                    key={ViewType.SESSIONS}
                    data-attr="insight-sessions-tab"
                />
                <TabPane
                    tab={<span data-attr="insight-funnels-tab">Funnels</span>}
                    key={ViewType.FUNNELS}
                    data-attr="insight-funnels-tab"
                />
                <TabPane tab={<span data-attr="insight-retention-tab">Retention</span>} key={ViewType.RETENTION} />
                <TabPane tab={<span data-attr="insight-path-tab">User Paths</span>} key={ViewType.PATHS} />
            </Tabs>
            <Row gutter={16}>
                <Col xs={24} xl={7}>
                    <Card>
                        <div className="card-body px-4">
                            {
                                /* Insight-specific filters, each with its specific logic */
                                insightFilters[activeView]
                            }
                        </div>
                    </Card>
                </Col>
                <Col xs={24} xl={17}>
                    {/* Filters that are reused between insight features, each with URL-updating logic */}
                    <Card
                        title={
                            <div className="float-right pt-1 pb-1">
                                {showChartFilter[activeView] && (
                                    <ChartFilter
                                        onChange={(displayMode: string) => {
                                            if (displayMode === ACTIONS_TABLE || displayMode === ACTIONS_PIE_CHART)
                                                clearAnnotationsToCreate()
                                        }}
                                        displayMap={displayMap}
                                        shouldShowIntervalFilter={shouldShowIntervalFilter}
                                        filters={allFilters}
                                        activeView={activeView}
                                    />
                                )}

                                {showDateFilter[activeView] && <DateFilter view={activeView} filters={allFilters} />}

                                {showComparePrevious[activeView] && <CompareFilter />}
                                <SaveToDashboard
                                    disabled={disableSaveToDashboard[activeView]}
                                    item={{
                                        type: determineInsightType(activeView, allFilters.display),
                                        entity:
                                            activeView === ViewType.FUNNELS
                                                ? allFilters
                                                : {
                                                      filters: allFilters,
                                                      annotations: annotationsToCreate,
                                                  },
                                    }}
                                />
                            </div>
                        }
                    >
                        <div className="card-body card-body-graph">{insightGraphs[activeView]}</div>
                    </Card>
                    {allFilters.display === FUNNEL_STEPS && <FunnelPeople />}
                </Col>
            </Row>
        </div>
    )
})
