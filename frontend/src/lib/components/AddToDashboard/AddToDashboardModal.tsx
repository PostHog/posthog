import { IconHome } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { addToDashboardModalLogic } from 'lib/components/AddToDashboard/addToDashboardModalLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils'
import { CSSProperties } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { canEditInsight } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardBasicType, InsightModel } from '~/types'

interface DashboardRelationRowProps {
    dashboard: DashboardBasicType
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
            <Link
                to={urls.dashboard(dashboard.id)}
                className="overflow-hidden text-ellipsis whitespace-nowrap"
                title={dashboard.name}
            >
                {dashboard.name || 'Untitled'}
            </Link>
            {isPrimary && (
                <Tooltip title="Primary dashboards are shown on the project home page">
                    <span className="flex items-center">
                        <IconHome className="text-warning text-base" />
                    </span>
                </Tooltip>
            )}
            <span className="grow" />
            <LemonButton
                type="secondary"
                status={isAlreadyOnDashboard ? 'danger' : 'default'}
                loading={dashboardWithActiveAPICall === dashboard.id}
                disabledReason={
                    !canEditInsight
                        ? "You don't have permission to edit this dashboard"
                        : dashboardWithActiveAPICall
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
                {isAlreadyOnDashboard ? 'Remove from dashboard' : 'Add to dashboard'}
            </LemonButton>
        </div>
    )
}

export function AddToDashboardContent({ insight }: { insight: Partial<InsightModel> }): JSX.Element {
    const logic = addToDashboardModalLogic({
        insight: insight,
    })

    const _canEditInsight = canEditInsight(insight)

    const { searchQuery, currentDashboards, orderedDashboards, scrollIndex } = useValues(logic)
    const { setSearchQuery } = useActions(logic)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        return (
            <DashboardRelationRow
                key={rowIndex}
                dashboard={orderedDashboards[rowIndex]}
                insight={insight}
                canEditInsight={_canEditInsight}
                isHighlighted={rowIndex === scrollIndex}
                isAlreadyOnDashboard={currentDashboards.some(
                    (currentDashboard) => currentDashboard.id === orderedDashboards[rowIndex].id
                )}
                style={style}
            />
        )
    }

    return (
        <div className="space-y-2 w-192 max-w-full">
            <LemonInput
                data-attr="dashboard-searchfield"
                type="search"
                fullWidth
                placeholder="Search for dashboards..."
                value={searchQuery}
                onChange={(newValue) => setSearchQuery(newValue)}
            />
            <div className="text-muted-alt">
                This insight is referenced on <strong className="text-default">{currentDashboards.length}</strong>{' '}
                {pluralize(currentDashboards.length, 'dashboard', 'dashboards', false)}
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
    )
}

export function openAddToDashboardModal(insight: Partial<InsightModel>): void {
    const _canEditInsight = canEditInsight(insight)
    LemonDialog.open({
        title: 'Add to dashboard',
        content: (
            <>
                <AddToDashboardContent insight={insight} />
            </>
        ),
        primaryButton: {
            type: 'secondary',
            children: 'Close',
        },
        tertiaryButton: {
            children: 'Add to a new dashboard',
            disabledReason: !_canEditInsight
                ? 'You do not have permission to add this insight to dashboards'
                : undefined,

            onClick: () => addToDashboardModalLogic.findMounted({ insight })?.actions.addNewDashboard(),
            closeOnClick: false,
        },
    })
}
