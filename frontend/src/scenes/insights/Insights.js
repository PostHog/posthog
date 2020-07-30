import React, { useState } from 'react'
import { useActions, useValues } from 'kea'

import { Card, Loading } from 'lib/utils'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { DateFilter } from 'lib/components/DateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter/IntervalFilter'

import { ActionsPie } from './ActionsPie'
import { ActionsTable } from './ActionsTable'
import { ActionsLineGraph } from './ActionsLineGraph'
import { PeopleModal } from './PeopleModal'

import { ChartFilter } from 'lib/components/ChartFilter'
import { Tabs, Row, Col } from 'antd'
import {
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    LINEAR_CHART_LABEL,
    CUMULATIVE_CHART_LABEL,
    TABLE_LABEL,
    PIE_CHART_LABEL,
    ACTIONS_TABLE,
    ACTIONS_PIE_CHART,
    RETENTION_TABLE,
    PATHS_VIZ,
    FUNNEL_VIZ,
} from 'lib/constants'
import { hot } from 'react-hot-loader/root'
import { annotationsLogic } from '~/lib/components/Annotations'
import { router } from 'kea-router'

import { RetentionTable } from 'scenes/retention/RetentionTable'

import { Paths } from 'scenes/paths/Paths'

import { RetentionTab, SessionTab, TrendTab, PathTab, FunnelTab } from './InsightTabs'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { People } from 'scenes/funnels/People'
import { insightLogic, ViewType } from './insightLogic'
import { trendsLogic } from './trendsLogic'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { InsightHistoryPanel } from './InsightHistoryPanel'

const { TabPane } = Tabs

const displayMap = {
    [`${ACTIONS_LINE_GRAPH_LINEAR}`]: LINEAR_CHART_LABEL,
    [`${ACTIONS_LINE_GRAPH_CUMULATIVE}`]: CUMULATIVE_CHART_LABEL,
    [`${ACTIONS_TABLE}`]: TABLE_LABEL,
    [`${ACTIONS_PIE_CHART}`]: PIE_CHART_LABEL,
}

const showIntervalFilter = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: false,
    [`${ViewType.RETENTION}`]: false,
    [`${ViewType.PATHS}`]: false,
}

const showChartFilter = {
    [`${ViewType.TRENDS}`]: true,
    [`${ViewType.SESSIONS}`]: true,
    [`${ViewType.FUNNELS}`]: false,
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

function determineInsightType(activeView, display) {
    if (activeView === ViewType.TRENDS || activeView === ViewType.SESSIONS) {
        return display || ACTIONS_LINE_GRAPH_LINEAR
    } else if (activeView === ViewType.FUNNELS) {
        return FUNNEL_VIZ
    } else if (activeView === ViewType.RETENTION) {
        return RETENTION_TABLE
    } else if (activeView === ViewType.PATHS) {
        return PATHS_VIZ
    } else {
        return null
    }
}

export const Insights = hot(_Insights)
function _Insights() {
    const [{ fromItem }] = useState(router.values.hashParams)
    const { clearAnnotationsToCreate } = useActions(annotationsLogic({ pageKey: fromItem }))
    const { annotationsToCreate } = useValues(annotationsLogic({ pageKey: fromItem }))

    const { activeView, allFilters } = useValues(insightLogic)
    const { setActiveView } = useActions(insightLogic)

    return (
        <div className="actions-graph">
            <h1 className="page-header">Insights</h1>
            <Tabs
                size="large"
                activeKey={activeView}
                style={{
                    overflow: 'visible',
                }}
                onChange={(key) => setActiveView(key)}
                animated={false}
            >
                <TabPane
                    tab={<span data-attr="insight-trends-tab">Trends</span>}
                    key={ViewType.TRENDS}
                    data-attr="insight-trend-tab"
                ></TabPane>
                <TabPane
                    tab={<span data-attr="insight-sessions-tab">Sessions</span>}
                    key={ViewType.SESSIONS}
                    data-attr="insight-sessions-tab"
                ></TabPane>
                <TabPane
                    tab={<span data-attr="insight-funnels-tab">Funnels</span>}
                    key={ViewType.FUNNELS}
                    data-attr="insight-funnels-tab"
                ></TabPane>
                <TabPane
                    tab={<span data-attr="insight-retention-tab">Retention</span>}
                    key={ViewType.RETENTION}
                ></TabPane>
                <TabPane tab={<span data-attr="insight-path-tab">User Paths</span>} key={ViewType.PATHS}></TabPane>
            </Tabs>
            <Row gutter={16}>
                <Col xs={24} xl={7}>
                    <Card>
                        <div className="card-body px-4">
                            {/* 
                            These are insight specific filters. 
                            They each have insight specific logics
                            */}
                            {
                                {
                                    [`${ViewType.TRENDS}`]: <TrendTab></TrendTab>,
                                    [`${ViewType.SESSIONS}`]: <SessionTab />,
                                    [`${ViewType.FUNNELS}`]: <FunnelTab></FunnelTab>,
                                    [`${ViewType.RETENTION}`]: <RetentionTab></RetentionTab>,
                                    [`${ViewType.PATHS}`]: <PathTab></PathTab>,
                                }[activeView]
                            }
                        </div>
                    </Card>
                    <Card>
                        <div className="card-body px-4">
                            <InsightHistoryPanel />
                        </div>
                    </Card>
                </Col>
                <Col xs={24} xl={17}>
                    {/* 
                    These are filters that are reused between insight features. 
                    They each have generic logic that updates the url
                    */}
                    <Card
                        title={
                            <div className="float-right pt-1 pb-1">
                                {showIntervalFilter[activeView] && (
                                    <IntervalFilter filters={allFilters} view={activeView} />
                                )}
                                {showChartFilter[activeView] && (
                                    <ChartFilter
                                        onChange={(display) => {
                                            if (display === ACTIONS_TABLE || display === ACTIONS_PIE_CHART)
                                                clearAnnotationsToCreate()
                                        }}
                                        displayMap={displayMap}
                                        filters={allFilters}
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
                        <div className="card-body card-body-graph">
                            {
                                {
                                    [`${ViewType.TRENDS}`]: <TrendInsight view={ViewType.TRENDS}></TrendInsight>,
                                    [`${ViewType.SESSIONS}`]: <TrendInsight view={ViewType.SESSIONS}></TrendInsight>,
                                    [`${ViewType.FUNNELS}`]: <FunnelInsight></FunnelInsight>,
                                    [`${ViewType.RETENTION}`]: <RetentionTable />,
                                    [`${ViewType.PATHS}`]: <Paths />,
                                }[activeView]
                            }
                        </div>
                    </Card>
                    {activeView === ViewType.FUNNELS && (
                        <Card>
                            <FunnelPeople></FunnelPeople>
                        </Card>
                    )}
                </Col>
            </Row>
        </div>
    )
}

function TrendInsight({ view }) {
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

function FunnelInsight() {
    const { funnel, funnelLoading, stepsWithCount, stepsWithCountLoading } = useValues(funnelLogic({ id: null }))
    if (!funnel && funnelLoading) return <Loading />
    return (
        <div style={{ height: 300 }}>
            {stepsWithCountLoading && <Loading />}
            {stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1 ? (
                <FunnelViz funnel={{ steps: stepsWithCount }} />
            ) : (
                <div
                    style={{
                        textAlign: 'center',
                    }}
                >
                    <span>Enter the details to your funnel and click 'save' to create a funnel visualization</span>
                </div>
            )}
        </div>
    )
}

function FunnelPeople() {
    const { funnel } = useValues(funnelLogic({ id: null }))
    if (funnel.id) {
        return (
            <div className="funnel">
                <People />
            </div>
        )
    }
    return <></>
}
