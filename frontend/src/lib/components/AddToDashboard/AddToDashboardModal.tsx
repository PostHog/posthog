import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useActions, useValues } from 'kea'
import { addToDashboardModalLogic } from 'lib/components/AddToDashboard/addToDashboardModalLogic'
import { urls } from 'scenes/urls'
import './AddToDashboard.scss'
import { IconCottage } from 'lib/lemon-ui/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { DashboardType, InsightModel } from '~/types'
import clsx from 'clsx'
import { pluralize } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { CSSProperties } from 'react'

interface SaveToDashboardModalProps {
    isOpen: boolean
    closeModal: () => void
    insight: Partial<InsightModel>
    canEditInsight: boolean
}

interface DashboardRelationRowProps {
    dashboard: DashboardType
    insight: Partial<InsightModel>
    canEditInsight: boolean
    isHighlighted: boolean
    isAlreadyOnDashboard: boolean
    style: CSSProperties
}

const DashboardRelationRow = ({
    style,
    isHighlighted,
    isAlreadyOnDashboard,
    dashboard,
    insight,
    canEditInsight,
}: DashboardRelationRowProps): JSX.Element => {
    const logic = addToDashboardModalLogic({
        insight: insight,
        fromDashboard: insight.dashboards?.[0] || undefined,
    })
    const { addToDashboard, removeFromDashboard } = useActions(logic)
    const { dashboardWithActiveAPICall } = useValues(logic)

    const { currentTeam } = useValues(teamLogic)
    const isPrimary = dashboard.id === currentTeam?.primary_dashboard
    return (
        <div
            data-attr="dashboard-list-item"
            /* eslint-disable-next-line react/forbid-dom-props */
            style={style}
            className={clsx('flex items-center space-x-2', isHighlighted && 'highlighted')}
        >
            <Link to={urls.dashboard(dashboard.id)}>{dashboard.name || 'Untitled'}</Link>
            {isPrimary && (
                <Tooltip title="Primary dashboards are shown on the project home page">
                    <IconCottage className="text-warning text-base" />
                </Tooltip>
            )}
            <span className="grow" />
            <LemonButton
                type={isAlreadyOnDashboard ? 'primary' : 'secondary'}
                loading={dashboardWithActiveAPICall === dashboard.id}
                disabledReason={
                    !canEditInsight
                        ? "You don't have permission to edit this dashboard"
                        : !!dashboardWithActiveAPICall
                        ? 'Loading...'
                        : ''
                }
                size="small"
                onClick={(e) => {
                    e.preventDefault()
                    isAlreadyOnDashboard
                        ? removeFromDashboard(insight, dashboard.id)
                        : addToDashboard(insight, dashboard.id)
                }}
            >
                {isAlreadyOnDashboard ? 'Added' : 'Add to dashboard'}
            </LemonButton>
        </div>
    )
}

export function AddToDashboardModal({
    isOpen,
    closeModal,
    insight,
    canEditInsight,
}: SaveToDashboardModalProps): JSX.Element {
    const logic = addToDashboardModalLogic({
        insight: insight,
        fromDashboard: insight.dashboards?.[0] || undefined,
    })

    const { searchQuery, currentDashboards, orderedDashboards, scrollIndex } = useValues(logic)
    const { setSearchQuery, addNewDashboard } = useActions(logic)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        return (
            <DashboardRelationRow
                key={rowIndex}
                dashboard={orderedDashboards[rowIndex]}
                insight={insight}
                canEditInsight={canEditInsight}
                isHighlighted={rowIndex === scrollIndex}
                isAlreadyOnDashboard={currentDashboards.some(
                    (currentDashboard: DashboardType) => currentDashboard.id === orderedDashboards[rowIndex].id
                )}
                style={style}
            />
        )
    }

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={isOpen}
            title="Add to dashboard"
            footer={
                <>
                    <div className="flex-1">
                        <LemonButton
                            type="secondary"
                            onClick={addNewDashboard}
                            disabledReason={
                                !canEditInsight
                                    ? 'You do not have permission to add this Insight to dashboards'
                                    : undefined
                            }
                        >
                            Add to a new dashboard
                        </LemonButton>
                    </div>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <LemonInput
                    data-attr="dashboard-searchfield"
                    type="search"
                    fullWidth
                    placeholder={`Search for dashboards...`}
                    value={searchQuery}
                    onChange={(newValue) => setSearchQuery(newValue)}
                />
                <div className="text-muted-alt">
                    This insight is referenced on{' '}
                    <strong className="text-default">{insight.dashboard_tiles?.length}</strong>{' '}
                    {pluralize(insight.dashboard_tiles?.length || 0, 'dashboard', 'dashboards', false)}
                </div>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ minHeight: 420 }}>
                    <AutoSizer>
                        {({ height, width }) => (
                            <List
                                width={width}
                                height={height}
                                rowCount={orderedDashboards.length}
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
