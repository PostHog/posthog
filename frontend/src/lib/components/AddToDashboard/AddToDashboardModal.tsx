import React from 'react'
import { Tooltip } from 'lib/components/Tooltip'
import { useActions, useValues } from 'kea'
import { addToDashboardModalLogic } from 'lib/components/AddToDashboard/addToDashboardModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'
import './AddToDashboard.scss'
import { IconMagnifier, IconCottage } from 'lib/components/icons'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { LemonButton } from 'lib/components/LemonButton'
import { Link } from 'lib/components/Link'
import { DashboardType, InsightModel } from '~/types'
import clsx from 'clsx'
import { LemonModal } from 'lib/components/LemonModal'
import { pluralize } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

interface SaveToDashboardModalProps {
    visible: boolean
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
    style: React.CSSProperties
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
        <div style={style} className={clsx('modal-row', isHighlighted && 'highlighted')}>
            <span>
                <Link to={urls.dashboard(dashboard.id)}>{dashboard.name || 'Untitled'}</Link>
                {isPrimary && (
                    <Tooltip title="Primary dashboards are shown on the project home page">
                        <IconCottage
                            style={{
                                marginLeft: 6,
                                color: 'var(--warning)',
                                fontSize: '1rem',
                                verticalAlign: '-0.125em',
                            }}
                        />
                    </Tooltip>
                )}
            </span>
            <LemonButton
                type={isAlreadyOnDashboard ? 'primary' : 'secondary'}
                loading={dashboardWithActiveAPICall === dashboard.id}
                disabled={!!dashboardWithActiveAPICall || !canEditInsight}
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
    visible,
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

    const { insightLoading } = useValues(insightLogic)

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
            onCancel={closeModal}
            afterClose={closeModal}
            confirmLoading={insightLoading}
            visible={visible}
            wrapClassName="add-to-dashboard-modal"
        >
            <section>
                <h5>Add to dashboard</h5>
                <LemonInput
                    data-attr="dashboard-searchfield"
                    placeholder={`Search for dashboards...`}
                    value={searchQuery}
                    className={searchQuery && 'LemonInput--with-input'}
                    icon={<IconMagnifier />}
                    onChange={(newValue) => setSearchQuery(newValue)}
                />
                <div className={'existing-links-info'}>
                    This insight is referenced on <strong>{insight.dashboards?.length}</strong>{' '}
                    {pluralize(insight.dashboards?.length || 0, 'dashboard', 'dashboards', false)}
                </div>
                <div className="list-wrapper">
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
            </section>
            <section className="space-between-items">
                <LemonButton type="secondary" size="small" onClick={addNewDashboard} disabled={!canEditInsight}>
                    Add to a new dashboard
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={closeModal}
                    style={{ marginTop: 0 }} /* lemon section styling was adding a margin top */
                >
                    Close
                </LemonButton>
            </section>
        </LemonModal>
    )
}
