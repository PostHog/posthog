import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CSSProperties } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { urls } from 'scenes/urls'

import { DashboardType, InsightModel, InsightShortId } from '~/types'

import { addInsightFromDashboardModalLogic } from './addInsightFromDashboardModalLogic'

interface AddInsightFromDashboardModalProps {
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
    // canEditDashboard,
    // isHighlighted,
    isAlreadyOnDashboard,
    style,
}: InsightRelationRowProps): JSX.Element => {
    const logic = addInsightFromDashboardModalLogic({
        dashboard: dashboard,
        insight: insight,
    })

    const { addToDashboard, removeFromDashboard } = useActions(logic)

    return (
        <div
            data-attr="dashboard-list-item"
            /* eslint-disable-next-line react/forbid-dom-props */
            style={style}
            className="flex items-center space-x-2"
        >
            <Link
                to={urls.insightEdit(insight.short_id)}
                className="overflow-hidden text-ellipsis whitespace-nowrap"
                title={insight.name}
            >
                {insight.name || 'Untitled'}
            </Link>
            <span className="grow" />
            <LemonButton
                type="secondary"
                status={isAlreadyOnDashboard ? 'danger' : 'default'}
                size="small"
                onClick={(e) => {
                    e.preventDefault()
                    isAlreadyOnDashboard ? removeFromDashboard() : addToDashboard()
                }}
            >
                {isAlreadyOnDashboard ? 'Remove from dashboard' : 'Add to dashboard'}
            </LemonButton>
        </div>
    )
}

export function AddInsightFromDashboardModal({
    isOpen,
    closeModal,
    dashboard,
    canEditDashboard,
}: AddInsightFromDashboardModalProps): JSX.Element | null {
    const logic = addInsightFromDashboardModalLogic({
        dashboard: dashboard,
    })

    const { searchQuery, filteredInsights, scrollIndex } = useValues(logic)

    const { setSearchQuery } = useActions(logic)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const dashboardInsightIds = dashboard.tiles
            .map((tile) => tile.insight?.short_id)
            .filter((id) => id !== undefined) as InsightShortId[]

        return (
            <InsightRelationRow
                key={rowIndex}
                dashboard={dashboard}
                insight={filteredInsights[rowIndex]}
                canEditDashboard={canEditDashboard}
                isHighlighted={rowIndex === scrollIndex}
                isAlreadyOnDashboard={dashboardInsightIds.some((id) => id == filteredInsights[rowIndex].short_id)}
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
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                </>
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
