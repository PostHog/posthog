import React from 'react'
import { useActions, useValues } from 'kea'

import { Card, CloseButton, Loading } from 'lib/utils'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DateFilter } from 'lib/components/DateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'

import { ActionFilter } from './ActionFilter/ActionFilter'
import { ActionsPie } from './ActionsPie'
import { BreakdownFilter } from './BreakdownFilter'
import { ActionsTable } from './ActionsTable'
import { ActionsLineGraph } from './ActionsLineGraph'
import { ShownAsFilter } from './ShownAsFilter'
import { PeopleModal } from './PeopleModal'
import { trendsLogic, ViewType } from './trendsLogic'
import { ChartFilter } from 'lib/components/ChartFilter'
import { Tabs, Row, Col, Tooltip, Checkbox } from 'antd'
import { SessionFilter } from 'lib/components/SessionsFilter'
import { InfoCircleOutlined } from '@ant-design/icons'
import {
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    LINEAR_CHART_LABEL,
    CUMULATIVE_CHART_LABEL,
} from 'lib/constants'
import { hot } from 'react-hot-loader/root'

const { TabPane } = Tabs

const displayMap = {
    [`${ACTIONS_LINE_GRAPH_LINEAR}`]: LINEAR_CHART_LABEL,
    [`${ACTIONS_LINE_GRAPH_CUMULATIVE}`]: CUMULATIVE_CHART_LABEL,
    ActionsTable: 'Table',
    ActionsPie: 'Pie',
}

export const Trends = hot(_Trends)
function _Trends() {
    const { filters, resultsLoading, showingPeople, activeView } = useValues(trendsLogic({ dashboardItemId: null }))
    const { setFilters, setDisplay, setActiveView } = useActions(trendsLogic({ dashboardItemId: null }))

    return (
        <div className="actions-graph">
            <PeopleModal visible={showingPeople} />
            <h1 className="page-header">Trends</h1>
            <Row gutter={16}>
                <Col xs={24} xl={7}>
                    <Card>
                        <div className="card-body px-4">
                            <Tabs
                                activeKey={activeView}
                                style={{
                                    overflow: 'visible',
                                }}
                                onChange={key => setActiveView(key)}
                                animated={false}
                            >
                                <TabPane tab={'Actions & Events'} key={ViewType.FILTERS}>
                                    <ActionFilter filters={filters} setFilters={setFilters} typeKey="trends" />
                                    <hr />
                                    <h4 className="secondary">Filters</h4>
                                    <PropertyFilters pageKey="trends-filters" style={{ marginBottom: 0 }} />
                                    <hr />
                                    <h4 className="secondary">
                                        Break down by
                                        <Tooltip
                                            placement="right"
                                            title="Use breakdown to see the volume of events for each variation of that property. For example, breaking down by $current_url will give you the event volume for each url your users have visited."
                                        >
                                            <InfoCircleOutlined
                                                className="info"
                                                style={{ color: '#007bff' }}
                                            ></InfoCircleOutlined>
                                        </Tooltip>
                                    </h4>
                                    <Row>
                                        <BreakdownFilter
                                            filters={filters}
                                            onChange={(breakdown, breakdown_type) =>
                                                setFilters({ breakdown, breakdown_type })
                                            }
                                        />
                                        {filters.breakdown && (
                                            <CloseButton
                                                onClick={() => setFilters({ breakdown: false, breakdown_type: null })}
                                                style={{ marginTop: 1, marginLeft: 10 }}
                                            />
                                        )}
                                    </Row>
                                    <hr />
                                    <h4 className="secondary">
                                        Shown as
                                        <Tooltip
                                            placement="right"
                                            title='
                                            Stickiness shows you how many days users performed an action within the timeframe. If a user
                                            performed an action on Monday and again on Friday, it would be shown 
                                            as "2 days".'
                                        >
                                            <InfoCircleOutlined
                                                className="info"
                                                style={{ color: '#007bff' }}
                                            ></InfoCircleOutlined>
                                        </Tooltip>
                                    </h4>
                                    <ShownAsFilter filters={filters} onChange={shown_as => setFilters({ shown_as })} />
                                </TabPane>
                                <TabPane tab="Sessions" key={ViewType.SESSIONS} data-attr="trends-sessions-tab">
                                    <SessionFilter value={filters.session} onChange={v => setFilters({ session: v })} />
                                    <hr />
                                    <h4 className="secondary">Filters</h4>
                                    <PropertyFilters pageKey="trends-sessions" style={{ marginBottom: 0 }} />
                                </TabPane>
                            </Tabs>
                        </div>
                    </Card>
                </Col>
                <Col xs={24} xl={17}>
                    <Card
                        title={
                            <div className="float-right pt-1 pb-1">
                                <IntervalFilter setFilters={setFilters} filters={filters} disabled={filters.session} />
                                <ChartFilter displayMap={displayMap} filters={filters} onChange={setDisplay} />
                                <DateFilter
                                    onChange={(date_from, date_to) =>
                                        setFilters({
                                            date_from: date_from,
                                            date_to: date_to && date_to,
                                            ...(['-24h', '-48h', 'dStart', '-1d'].indexOf(date_from) > -1
                                                ? { interval: 'hour' }
                                                : {}),
                                        })
                                    }
                                    dateFrom={filters.date_from}
                                    dateTo={filters.date_to}
                                />
                                <Checkbox
                                    onChange={e => {
                                        setFilters({ compare: e.target.checked })
                                    }}
                                    checked={filters.compare}
                                    style={{ marginLeft: 8, marginRight: 6 }}
                                >
                                    Compare Previous
                                </Checkbox>
                                <SaveToDashboard
                                    filters={filters}
                                    type={filters.display || ACTIONS_LINE_GRAPH_LINEAR}
                                />
                            </div>
                        }
                    >
                        <div className="card-body card-body-graph">
                            {(filters.actions || filters.events || filters.session) && (
                                <div
                                    style={{
                                        minHeight: '70vh',
                                        position: 'relative',
                                    }}
                                >
                                    {resultsLoading && <Loading />}
                                    {(!filters.display ||
                                        filters.display === ACTIONS_LINE_GRAPH_LINEAR ||
                                        filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE) && <ActionsLineGraph />}
                                    {filters.display === 'ActionsTable' && <ActionsTable filters={filters} />}
                                    {filters.display === 'ActionsPie' && <ActionsPie filters={filters} />}
                                </div>
                            )}
                        </div>
                    </Card>
                </Col>
            </Row>
        </div>
    )
}
