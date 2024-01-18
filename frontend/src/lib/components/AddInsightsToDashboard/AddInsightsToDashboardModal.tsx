import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CSSProperties } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { urls } from 'scenes/urls'

import { DashboardType, InsightModel } from '~/types'

import { addInsightsToDashboardModalLogic } from './addInsightsToDashboardModalLogic'

interface AddInsightsToDashboardModalProps {
    isOpen: boolean
    closeModal: () => void
    dashboard: DashboardType
    canEditDashboard: boolean
}

interface InsightRelationRowProps {
    dashboard: DashboardType
    insight: InsightModel
    canEditDashboard: boolean
    isHighlighted: boolean
    isAlreadyOnDashboard: boolean
    style: CSSProperties
}

const InsightRelationRow = ({
    dashboard,
    insight,
    canEditDashboard,
    isHighlighted,
    isAlreadyOnDashboard,
    style,
}: InsightRelationRowProps): JSX.Element => {
    const logic = addInsightsToDashboardModalLogic({
        dashboard: dashboard,
    })

    const { addToDashboard, removeFromDashboard } = useActions(logic)

    const { insightWithActiveAPICall } = useValues(logic)

    return (
        <div
            data-attr="dashboard-list-item"
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

export function AddInsightsToDashboardModal({
    isOpen,
    closeModal,
    dashboard,
    canEditDashboard,
}: AddInsightsToDashboardModalProps): JSX.Element | null {
    const logic = addInsightsToDashboardModalLogic({
        dashboard: dashboard,
    })

    const { searchQuery, filteredInsights, scrollIndex } = useValues(logic)

    const { setSearchQuery } = useActions(logic)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        return (
            <InsightRelationRow
                key={filteredInsights[rowIndex].short_id}
                dashboard={dashboard}
                insight={filteredInsights[rowIndex]}
                canEditDashboard={canEditDashboard}
                isHighlighted={rowIndex === scrollIndex}
                isAlreadyOnDashboard={
                    logic.values.tiles?.some((t) => t.insight?.short_id === filteredInsights[rowIndex].short_id) ||
                    false
                }
                style={style}
            />
        )
    }

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            title="Add Insights to Dashboard"
            footer={
                <div className="w-full flex justify-between">
                    <LemonButton to={urls.insightNew(undefined, dashboard.id)} type="secondary">
                        Create New Insight
                    </LemonButton>
                    <LemonButton type="secondary" onClick={closeModal}>
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
                    placeholder={`Search for insights...`}
                    value={searchQuery}
                    onChange={(newValue) => setSearchQuery(newValue)}
                />
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ minHeight: 420 }}>
                    <AutoSizer>
                        {({ height, width }) => (
                            <List
                                width={width}
                                height={height}
                                rowCount={filteredInsights.length}
                                overscanRowCount={100}
                                rowHeight={40}
                                rowRenderer={renderItem}
                                scrollToIndex={scrollIndex}
                            />
                        )}
                    </AutoSizer>
                </div>
            </div>
        </LemonModal>
    )
}
