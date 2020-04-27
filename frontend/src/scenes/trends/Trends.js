import React from 'react'
import { useActions, useValues } from 'kea'

import { Card, CloseButton, Loading } from 'lib/utils'
import { SaveToDashboard } from 'lib/components/SaveToDashboard'
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
import { userLogic } from 'scenes/userLogic'
import { Tabs, Row, Col, Tooltip } from 'antd'
import { SessionFilter } from 'lib/components/SessionsFilter'
import { useWindowSize } from 'lib/hooks/useWindowSize'

const { TabPane } = Tabs

const displayMap = {
    ActionsLineGraph: 'Line chart',
    ActionsTable: 'Table',
    ActionsPie: 'Pie',
}

export function Trends() {
    const { filters, resultsLoading, showingPeople, activeView } = useValues(trendsLogic({ dashboardItemId: null }))
    const { setFilters, setDisplay, setActiveView } = useActions(trendsLogic({ dashboardItemId: null }))
    const { eventProperties } = useValues(userLogic)
    const size = useWindowSize()

    return (
        <div className="actions-graph">
            {showingPeople ? <PeopleModal /> : null}
            <h1>Trends</h1>
            <Row gutter={16}>
                <Col xs={24} xl={6}>
                    <Card>
                        <div className="card-body px-4">
                            <Tabs
                                defaultActiveKey={activeView}
                                style={{
                                    overflow: 'visible',
                                }}
                                onChange={key => setActiveView(key)}
                                animated={false}
                            >
                                <TabPane tab={'Actions & Events'} key={ViewType.FILTERS}>
                                    <ActionFilter
                                        setDefaultIfEmpty={true}
                                        setFilters={setFilters}
                                        defaultFilters={filters}
                                        showMaths={true}
                                        typeKey="trends"
                                    />
                                    <hr />
                                    <h4 className="secondary">Filters</h4>
                                    <PropertyFilters
                                        pageKey="trends-filters"
                                        properties={eventProperties}
                                        propertyFilters={filters.properties}
                                        onChange={properties => setFilters({ properties })}
                                        style={{ marginBottom: 0 }}
                                    />
                                    <hr />
                                    <h4 className="secondary">
                                        Break down by
                                        <Tooltip
                                            placement="right"
                                            title="Use breakdown to see the volume of events for each variation of that property. For example, breaking down by $current_url will give you the event volume for each url your users have visited."
                                        >
                                            <small className="info">info</small>
                                        </Tooltip>
                                    </h4>
                                    <Row>
                                        <BreakdownFilter
                                            properties={eventProperties}
                                            breakdown={filters.breakdown}
                                            onChange={breakdown => setFilters({ breakdown })}
                                        />
                                        {filters.breakdown && (
                                            <CloseButton
                                                onClick={() => setFilters({ breakdown: false })}
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
                                            <small className="info">info</small>
                                        </Tooltip>
                                    </h4>
                                    <ShownAsFilter
                                        shown_as={filters.shown_as}
                                        onChange={shown_as => setFilters({ shown_as })}
                                    />
                                </TabPane>
                                <TabPane tab="Sessions" key={ViewType.SESSIONS}>
                                    <SessionFilter value={filters.session} onChange={v => setFilters({ session: v })} />
                                    <hr />
                                    <h4 className="secondary">Filters</h4>
                                    <PropertyFilters
                                        pageKey="trends-sessions"
                                        properties={eventProperties}
                                        propertyFilters={filters.properties}
                                        onChange={properties => setFilters({ properties })}
                                        style={{ marginBottom: 0 }}
                                    />
                                </TabPane>
                            </Tabs>
                        </div>
                    </Card>
                </Col>
                <Col xs={24} xl={18}>
                    <Card
                        title={
                            <div className="float-right pt-1 pb-1">
                                <IntervalFilter
                                    setFilters={setFilters}
                                    filters={filters}
                                    disabled={filters.breakdown || filters.session}
                                />
                                <ChartFilter
                                    displayMap={displayMap}
                                    filters={filters}
                                    onChange={setDisplay}
                                ></ChartFilter>
                                <DateFilter
                                    onChange={(date_from, date_to) =>
                                        setFilters({
                                            date_from: date_from,
                                            date_to: date_to && date_to,
                                        })
                                    }
                                    dateFrom={filters.date_from}
                                    dateTo={filters.date_to}
                                />
                                <SaveToDashboard filters={filters} type={filters.display || 'ActionsLineGraph'} />
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
                                    {(!filters.display || filters.display == 'ActionsLineGraph') && (
                                        <ActionsLineGraph />
                                    )}
                                    {filters.display == 'ActionsTable' && <ActionsTable filters={filters} />}
                                    {filters.display == 'ActionsPie' && <ActionsPie filters={filters} />}
                                </div>
                            )}
                        </div>
                    </Card>
                </Col>
            </Row>
        </div>
    )
}
