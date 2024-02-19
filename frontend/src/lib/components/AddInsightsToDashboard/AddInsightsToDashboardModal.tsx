import { LemonButton, LemonInput, LemonModal, Link, PaginationControl, usePagination } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CSSProperties } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { urls } from 'scenes/urls'

import { InsightModel } from '~/types'

import { addInsightsToDashboardModalLogic } from './addInsightsToDashboardModalLogic'

interface InsightRelationRowProps {
    dashboardId?: number
    insight: InsightModel
    canEditDashboard: boolean
    isHighlighted: boolean
    isAlreadyOnDashboard: boolean
    style: CSSProperties
}

const InsightRelationRow = ({
    dashboardId,
    insight,
    canEditDashboard,
    isHighlighted,
    isAlreadyOnDashboard,
    style,
}: InsightRelationRowProps): JSX.Element => {
    const logic = addInsightsToDashboardModalLogic({
        dashboardId: dashboardId,
    })

    const { addToDashboard, removeFromDashboard } = useActions(logic)

    const { insightWithActiveAPICall } = useValues(logic)

    return (
        <div
            data-attr="insight-list-item"
            /* eslint-disable-next-line react/forbid-dom-props */
            style={style}
            className={clsx('flex items-center space-x-2', isHighlighted && 'highlighted')}
        >
            <Link
                to={urls.insightEdit(insight.short_id)}
                className="overflow-hidden text-ellipsis whitespace-nowrap"
                title={insight.name}
            >
                {insight.name || insight.derived_name || 'Untitled'}
            </Link>
            <span className="grow" />
            <LemonButton
                type="secondary"
                status={isAlreadyOnDashboard ? 'danger' : 'default'}
                size="small"
                loading={insightWithActiveAPICall === insight.short_id || false}
                disabledReason={
                    !canEditDashboard
                        ? "You don't have permission to edit this dashboard"
                        : insightWithActiveAPICall
                        ? 'Loading...'
                        : ''
                }
                onClick={(e) => {
                    e.preventDefault()
                    isAlreadyOnDashboard ? removeFromDashboard(insight) : addToDashboard(insight)
                }}
            >
                {isAlreadyOnDashboard ? 'Remove from dashboard' : 'Add to dashboard'}
            </LemonButton>
        </div>
    )
}

export function AddInsightsToDashboardModal(): JSX.Element {
    const { insightsModalOpen, dashboard, canEditDashboard } = useValues(dashboardLogic)

    const { addInsightsModalOpen } = useActions(dashboardLogic)

    const logic = addInsightsToDashboardModalLogic({ dashboardId: dashboard?.id })

    const { searchQuery, insights, pagination, tiles, scrollIndex } = useValues(logic)

    const { setSearchQuery } = useActions(logic)

    const paginationState = usePagination(insights.results || [], pagination)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        return (
            <InsightRelationRow
                key={insights.results[rowIndex].short_id}
                dashboardId={dashboard?.id}
                insight={insights.results[rowIndex]}
                canEditDashboard={canEditDashboard}
                isHighlighted={rowIndex === scrollIndex}
                isAlreadyOnDashboard={
                    tiles?.some((t) => t.insight?.short_id === insights.results[rowIndex].short_id) || false
                }
                style={style}
            />
        )
    }

    return (
        <LemonModal
            onClose={() => addInsightsModalOpen(false)}
            isOpen={insightsModalOpen}
            title="Add insight to dashboard"
            footer={
                <div className="w-full flex justify-between" data-attr="dashboard-add-graph-footer">
                    <LemonButton to={urls.insightNew(undefined, dashboard?.id)} type="secondary">
                        Create a new insight
                    </LemonButton>
                    <LemonButton type="secondary" onClick={() => addInsightsModalOpen(false)}>
                        Close
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-2 w-192 max-w-full">
                <LemonInput
                    data-attr="insight-searchfield"
                    type="search"
                    fullWidth
                    placeholder="Search for insights..."
                    value={searchQuery}
                    onChange={(newValue) => setSearchQuery(newValue)}
                />
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ minHeight: 420 }}>
                    <AutoSizer>
                        {({ height, width }) => (
                            <List
                                style={{ paddingLeft: 10, paddingRight: 10 }}
                                width={width}
                                height={height}
                                rowCount={insights.results.length}
                                overscanRowCount={100}
                                rowHeight={40}
                                rowRenderer={renderItem}
                                scrollToIndex={scrollIndex}
                            />
                        )}
                    </AutoSizer>
                </div>
                <PaginationControl {...paginationState} nouns={['insight', 'insights']} bordered />
            </div>
        </LemonModal>
    )
}
