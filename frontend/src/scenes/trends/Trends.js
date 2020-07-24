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

export const Trends = hot(_Trends)
function _Trends() {
    const [{ fromItem }] = useState(router.values.hashParams)
    const { clearAnnotationsToCreate } = useActions(annotationsLogic({ pageKey: fromItem }))
    const { annotationsList } = useValues(annotationsLogic({ pageKey: fromItem }))

    const { activeView, allFilters } = useValues(insightLogic)
    const { setActiveView } = useActions(insightLogic)
    return (
        <div className="actions-graph">
            <h1 className="page-header">Insights</h1>
            <Row gutter={16}>
                <Col xs={24} xl={7}>
                    <Card>
                        <div className="card-body px-4">
                            <Tabs
                                activeKey={activeView}
                                style={{
                                    overflow: 'visible',
                                }}
                                onChange={(key) => setActiveView(key)}
                                animated={false}
                            >
                                <TabPane tab={'Trends'} key={ViewType.TRENDS} data-attr="insight-trend-tab">
                                    <TrendTab></TrendTab>
                                </TabPane>
                                <TabPane tab="Sessions" key={ViewType.SESSIONS} data-attr="insight-sessions-tab">
                                    <SessionTab />
                                </TabPane>
                                <TabPane tab="Funnels" key={ViewType.FUNNELS} data-attr="insight-funnels-tab">
                                    <FunnelTab></FunnelTab>
                                </TabPane>
                                <TabPane tab="Retention" key={ViewType.RETENTION} data-attr="insight-retention-tab">
                                    <RetentionTab></RetentionTab>
                                </TabPane>
                                <TabPane tab="User Paths" key={ViewType.PATHS} data-attr="insight-path-tab">
                                    <PathTab></PathTab>
                                </TabPane>
                            </Tabs>
                        </div>
                    </Card>
                </Col>
                <Col xs={24} xl={17}>
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
                                    filters={allFilters}
                                    type={allFilters.display || ACTIONS_LINE_GRAPH_LINEAR}
                                    annotations={annotationsList}
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
            {stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1 && (
                <FunnelViz funnel={{ steps: stepsWithCount }} />
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
