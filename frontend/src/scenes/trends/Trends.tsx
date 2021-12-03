import React from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { PersonsModal } from './PersonsModal'
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
import { InsightType } from '~/types'
import { InsightsTable } from 'scenes/insights/InsightsTable'
import { Button } from 'antd'
import { personsModalLogic } from './personsModalLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

interface Props {
    view: InsightType
}

export function TrendInsight({ view }: Props): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible } = useActions(personsModalLogic)
    const {
        filters: _filters,
        loadMoreBreakdownUrl,
        breakdownValuesLoading,
        showModalActions,
    } = useValues(trendsLogic(insightProps))
    const { loadMoreBreakdownValues } = useActions(trendsLogic(insightProps))
    const { showingPeople } = useValues(personsModalLogic)
    const { saveCohortWithFilters } = useActions(personsModalLogic)
    const { reportCohortCreatedFromPersonsModal } = useActions(eventUsageLogic)

    const renderViz = (): JSX.Element | undefined => {
        if (
            !_filters.display ||
            _filters.display === ACTIONS_LINE_GRAPH_LINEAR ||
            _filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE ||
            _filters.display === ACTIONS_BAR_CHART
        ) {
            return <ActionsLineGraph filters={_filters} />
        }
        if (_filters.display === ACTIONS_TABLE) {
            if (view === InsightType.SESSIONS && _filters.session === 'dist') {
                return <ActionsTable filters={_filters} />
            }
            return (
                <BindLogic logic={trendsLogic} props={{ dashboardItemId: null, view, filters: null }}>
                    <InsightsTable
                        isLegend={false}
                        showTotalCount={view !== InsightType.SESSIONS}
                        filterKey={`trends_${view}`}
                        canEditSeriesNameInline={_filters.session !== 'avg'}
                    />
                </BindLogic>
            )
        }
        if (_filters.display === ACTIONS_PIE_CHART) {
            return <ActionsPie filters={_filters} />
        }
        if (_filters.display === ACTIONS_BAR_CHART_VALUE) {
            return <ActionsBarValueGraph filters={_filters} />
        }
    }

    return (
        <>
            {(_filters.actions || _filters.events || _filters.session) && (
                <div className="trends-insights-container">{renderViz()}</div>
            )}
            {_filters.breakdown && (
                <div className="mt text-center">
                    {loadMoreBreakdownUrl ? (
                        <>
                            <div className="text-muted mb">
                                For readability, <b>not all breakdown values are displayed</b>. Click below to load
                                them.
                            </div>
                            <div>
                                <Button
                                    style={{ textAlign: 'center', marginBottom: 16 }}
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
            <PersonsModal
                visible={showingPeople && !cohortModalVisible}
                view={view}
                filters={_filters}
                onSaveCohort={() => {
                    setCohortModalVisible(true)
                }}
                showModalActions={showModalActions}
            />
            <SaveCohortModal
                visible={cohortModalVisible}
                onOk={(title: string) => {
                    saveCohortWithFilters(title, _filters)
                    setCohortModalVisible(false)
                    reportCohortCreatedFromPersonsModal(_filters)
                }}
                onCancel={() => setCohortModalVisible(false)}
            />
        </>
    )
}
