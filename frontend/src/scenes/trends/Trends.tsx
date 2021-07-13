import React from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { PersonModal } from './PersonModal'
import {
    ACTIONS_LINE_GRAPH_LINEAR,
    ACTIONS_LINE_GRAPH_CUMULATIVE,
    ACTIONS_TABLE,
    ACTIONS_PIE_CHART,
    ACTIONS_BAR_CHART,
    ACTIONS_BAR_CHART_VALUE,
} from 'lib/constants'

import { ActionsPie, ActionsLineGraph, ActionsBarValueGraph, ActionsTable } from './viz'
import { SaveCohortModal } from './SaveCohortModal'
import { trendsLogic } from './trendsLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import { InsightsTable } from 'scenes/insights/InsightsTable'
import { Button } from 'antd'
import { personsModalLogic } from './personsModalLogic'

interface Props {
    view: ViewType
}

export function TrendInsight({ view }: Props): JSX.Element {
    const { cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible } = useActions(personsModalLogic)
    const { filters: _filters, loadMoreBreakdownUrl, breakdownValuesLoading, resultsLoading } = useValues(
        trendsLogic({ dashboardItemId: null, view, filters: null })
    )
    const { loadMoreBreakdownValues } = useActions(trendsLogic({ dashboardItemId: null, view, filters: null }))
    const { showingPeople } = useValues(personsModalLogic)
    const { saveCohortWithFilters, refreshCohort } = useActions(personsModalLogic)
    const renderViz = (): JSX.Element | undefined => {
        if (
            !_filters.display ||
            _filters.display === ACTIONS_LINE_GRAPH_LINEAR ||
            _filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE ||
            _filters.display === ACTIONS_BAR_CHART
        ) {
            return <ActionsLineGraph filters={_filters} view={view} />
        }
        if (_filters.display === ACTIONS_TABLE) {
            if (view === ViewType.SESSIONS && _filters.session === 'dist') {
                return <ActionsTable filters={_filters} view={view} />
            }
            return (
                <BindLogic logic={trendsLogic} props={{ dashboardItemId: null, view, filters: null }}>
                    <InsightsTable isLegend={false} showTotalCount={view !== ViewType.SESSIONS} />
                </BindLogic>
            )
        }
        if (_filters.display === ACTIONS_PIE_CHART) {
            return <ActionsPie filters={_filters} view={view} />
        }
        if (_filters.display === ACTIONS_BAR_CHART_VALUE) {
            return <ActionsBarValueGraph filters={_filters} view={view} />
        }
    }

    return (
        <>
            {(_filters.actions || _filters.events || _filters.session) && (
                <div
                    style={{
                        minHeight: 'calc(90vh - 16rem)',
                        position: 'relative',
                    }}
                >
                    {renderViz()}
                </div>
            )}
            {_filters.breakdown && !resultsLoading && (
                <div className="mt text-center">
                    {loadMoreBreakdownUrl ? (
                        <>
                            <div className="text-muted mb">
                                For readability, <b>not all breakdown values are displayed</b>. Click below to load
                                them.
                            </div>
                            <div>
                                <Button
                                    style={{ textAlign: 'center' }}
                                    onClick={loadMoreBreakdownValues}
                                    loading={breakdownValuesLoading}
                                >
                                    Load more breakdown values
                                </Button>
                            </div>
                        </>
                    ) : (
                        <span className="text-muted">
                            Showing <b>all breakdown values</b>
                        </span>
                    )}
                </div>
            )}
            <PersonModal
                visible={showingPeople && !cohortModalVisible}
                view={view}
                filters={_filters}
                onSaveCohort={() => {
                    refreshCohort()
                    setCohortModalVisible(true)
                }}
            />
            <SaveCohortModal
                visible={cohortModalVisible}
                onOk={(title: string) => {
                    saveCohortWithFilters(title, _filters)
                    setCohortModalVisible(false)
                }}
                onCancel={() => setCohortModalVisible(false)}
            />
        </>
    )
}
