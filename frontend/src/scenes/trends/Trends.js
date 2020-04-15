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
import { Tabs } from 'antd'
import api from 'lib/api'

const { TabPane } = Tabs
import { ChartFilter } from 'lib/components/ChartFilter'
import { SessionFilter } from 'lib/components/SessionsFilter'

const displayMap = {
    ActionsLineGraph: 'Line chart',
    ActionsTable: 'Table',
    ActionsPie: 'Pie',
}

export function Trends() {
    const { filters, properties, resultsLoading, showingPeople, activeView, session } = useValues(
        trendsLogic({ dashboardItemId: null })
    )
    const { setFilters, setDisplay, setActiveView, setSessionParams } = useActions(
        trendsLogic({ dashboardItemId: null })
    )

    return (
        <div className="actions-graph">
            {showingPeople ? <PeopleModal /> : null}
            <h1>Trends</h1>
            <Card>
                <div className="card-body">
                    <Tabs defaultActiveKey={activeView} onChange={key => setActiveView(key)} animated={false}>
                        <TabPane tab={'Actions & Events'} key={ViewType.FILTERS}>
                            <ActionFilter
                                setFilters={setFilters}
                                defaultFilters={filters}
                                showMaths={true}
                                typeKey="trends"
                            />
                            <hr />
                            <h4 className="secondary">Filters</h4>
                            <PropertyFilters
                                properties={properties}
                                propertyFilters={filters.properties || {}}
                                onChange={properties => setFilters({ properties })}
                                style={{ marginBottom: 0 }}
                            />
                            <hr />
                            <h4 className="secondary">Break down by</h4>
                            <div className="select-with-close">
                                <BreakdownFilter
                                    properties={properties}
                                    breakdown={filters.breakdown}
                                    onChange={breakdown => setFilters({ breakdown })}
                                />
                                {filters.breakdown && (
                                    <CloseButton
                                        onClick={() => setFilters({ breakdown: false })}
                                        style={{ marginTop: 1 }}
                                    />
                                )}
                            </div>
                            <hr />
                            <h4 className="secondary">Shown as</h4>
                            <ShownAsFilter
                                shown_as={filters.shown_as}
                                onChange={shown_as => setFilters({ shown_as })}
                            />
                        </TabPane>
                        <TabPane tab="Sessions" key={ViewType.SESSIONS}>
                            <SessionFilter onChange={v => setSessionParams({ math: v })} />
                            <hr />
                            <h4 className="secondary">Filters</h4>
                            <PropertyFilters
                                properties={properties}
                                propertyFilters={filters.properties}
                                onChange={properties => setFilters({ properties })}
                                style={{ marginBottom: 0 }}
                            />
                        </TabPane>
                    </Tabs>
                </div>
            </Card>
            <Card
                title={
                    <span>
                        Graph
                        <div className="float-right">
                            <IntervalFilter
                                setFilters={setFilters}
                                filters={filters}
                                interval={filters.interval}
                                onChange={interval => setFilters({ interval })}
                                disabled={activeView == ViewType.SESSIONS}
                            />
                            <ChartFilter
                                defaultValue={displayMap[filters.display || 'ActionsLineGraph']}
                                disabledOptions={disabledChartOptions(filters, activeView)}
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
                            <SaveToDashboard
                                onSubmit={(value, callback) => {
                                    api.create('api/dashboard', {
                                        filters: filters,
                                        type: filters.display || 'ActionsLineGraph',
                                        name: value,
                                    }).then(callback)
                                }}
                            />
                        </div>
                    </span>
                }
            >
                <div className="card-body card-body-graph">
                    {filters.actions && (
                        <div
                            style={{
                                minHeight: 'calc(70vh - 50px)',
                                position: 'relative',
                            }}
                        >
                            {resultsLoading && <Loading />}
                            {((activeView != ViewType.SESSIONS && !filters.display) ||
                                filters.display == 'ActionsLineGraph') && <ActionsLineGraph />}
                            {(filters.display == 'ActionsTable' || activeView == ViewType.SESSIONS) && (
                                <ActionsTable filters={filters} view={activeView} session={session} />
                            )}
                            {filters.display == 'ActionsPie' && <ActionsPie filters={filters} />}
                        </div>
                    )}
                </div>
            </Card>
        </div>
    )
}

const disabledChartOptions = (filters, view) => {
    if (view == ViewType.SESSIONS) {
        return ['ActionsLineGraph']
    } else if (filters.breakdown) {
        return ['ActionsPie', 'ActionsLineGraph']
    } else {
        return []
    }
}
