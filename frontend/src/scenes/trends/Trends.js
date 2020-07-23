import React, { useState } from 'react'
import { useActions, useValues } from 'kea'

import { Card, Loading } from 'lib/utils'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { DateFilter } from 'lib/components/DateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'

import { ActionsPie } from './ActionsPie'
import { ActionsTable } from './ActionsTable'
import { ActionsLineGraph } from './ActionsLineGraph'
import { PeopleModal } from './PeopleModal'
import { trendsLogic, ViewType } from './trendsLogic'
import { ChartFilter } from 'lib/components/ChartFilter'
import { Tabs, Row, Col, Checkbox } from 'antd'
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
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'

import { Paths } from 'scenes/paths/Paths'
import { pathsLogic } from 'scenes/paths/pathsLogic'

import { RetentionTab, SessionTab, TrendTab, PathTab, FunnelTab } from './InsightTabs'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

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
    [`${ViewType.RETENTION}`]: true,
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
    const { filters, resultsLoading, showingPeople, activeView } = useValues(trendsLogic({ dashboardItemId: null }))
    const { setFilters, setDisplay, setActiveView } = useActions(trendsLogic({ dashboardItemId: null }))
    const [{ fromItem }] = useState(router.values.hashParams)
    const { clearAnnotationsToCreate } = useActions(annotationsLogic({ pageKey: fromItem }))
    const { annotationsList } = useValues(annotationsLogic({ pageKey: fromItem }))

    const _pathsLogic = pathsLogic()
    const { paths, filter: pathFilter, pathsLoading } = useValues(_pathsLogic)
    const { setFilter: setPathFilter } = useActions(_pathsLogic)
    const _retentionLogic = retentionTableLogic()

    return (
        <div className="actions-graph">
            <PeopleModal visible={showingPeople} />
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
                                    <TrendTab
                                        filters={filters}
                                        onEntityChanged={(payload) => setFilters(payload)}
                                        onBreakdownChanged={(breakdownPayload) => setFilters(breakdownPayload)}
                                        onShownAsChanged={(shown_as) => setFilters({ shown_as })}
                                    ></TrendTab>
                                </TabPane>
                                <TabPane tab="Sessions" key={ViewType.SESSIONS} data-attr="insight-sessions-tab">
                                    <SessionTab filters={filters} onChange={(v) => setFilters({ session: v })} />
                                </TabPane>
                                <TabPane tab="Funnels" key={ViewType.FUNNELS} data-attr="insight-funnels-tab">
                                    <FunnelTab></FunnelTab>
                                </TabPane>
                                <TabPane tab="Retention" key={ViewType.RETENTION} data-attr="insight-retention-tab">
                                    <RetentionTab></RetentionTab>
                                </TabPane>
                                <TabPane tab="User Paths" key={ViewType.PATHS} data-attr="insight-path-tab">
                                    <PathTab
                                        onChange={(payload) => setPathFilter(payload)}
                                        filter={pathFilter}
                                    ></PathTab>
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
                                    <IntervalFilter setFilters={setFilters} filters={filters} />
                                )}
                                {showChartFilter[activeView] && (
                                    <ChartFilter
                                        displayMap={displayMap}
                                        filters={filters}
                                        onChange={(display) => {
                                            if (display === ACTIONS_TABLE || display === ACTIONS_PIE_CHART)
                                                clearAnnotationsToCreate()
                                            setDisplay(display)
                                        }}
                                    />
                                )}
                                {showDateFilter[activeView] && (
                                    <DateFilter
                                        onChange={(date_from, date_to) => {
                                            setFilters({
                                                date_from: date_from,
                                                date_to: date_to && date_to,
                                                ...(['-24h', '-48h', 'dStart', '-1d'].indexOf(date_from) > -1
                                                    ? { interval: 'hour' }
                                                    : {}),
                                            })
                                        }}
                                        dateFrom={filters.date_from}
                                        dateTo={filters.date_to}
                                    />
                                )}
                                {showComparePrevious[activeView] && (
                                    <Checkbox
                                        onChange={(e) => {
                                            setFilters({ compare: e.target.checked })
                                        }}
                                        checked={filters.compare}
                                        style={{ marginLeft: 8, marginRight: 6 }}
                                    >
                                        Compare Previous
                                    </Checkbox>
                                )}
                                <SaveToDashboard
                                    filters={filters}
                                    type={filters.display || ACTIONS_LINE_GRAPH_LINEAR}
                                    annotations={annotationsList}
                                />
                            </div>
                        }
                    >
                        <div className="card-body card-body-graph">
                            {
                                {
                                    [`${ViewType.TRENDS}`]: (
                                        <TrendInsight filters={filters} loading={resultsLoading}></TrendInsight>
                                    ),
                                    [`${ViewType.SESSIONS}`]: (
                                        <TrendInsight filters={filters} loading={resultsLoading}></TrendInsight>
                                    ),
                                    [`${ViewType.FUNNELS}`]: <FunnelInsight></FunnelInsight>,
                                    [`${ViewType.RETENTION}`]: <RetentionTable logic={_retentionLogic} />,
                                    [`${ViewType.PATHS}`]: (
                                        <Paths
                                            logic={_pathsLogic}
                                            paths={paths}
                                            pathsLoading={pathsLoading}
                                            filter={pathFilter}
                                        />
                                    ),
                                }[activeView]
                            }
                        </div>
                    </Card>
                </Col>
            </Row>
        </div>
    )
}

function TrendInsight({ filters, loading }) {
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
                        filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE) && <ActionsLineGraph />}
                    {filters.display === ACTIONS_TABLE && <ActionsTable filters={filters} />}
                    {filters.display === ACTIONS_PIE_CHART && <ActionsPie filters={filters} />}
                </div>
            )}
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
