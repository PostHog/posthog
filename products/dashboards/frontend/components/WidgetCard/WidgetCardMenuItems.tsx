import { DashboardTileRefreshDataButton } from 'lib/components/Cards/InsightCard/DashboardTileRefreshDataButton'
import { DashboardWidgetPlacementMenus } from 'lib/components/Cards/InsightCard/DashboardWidgetPlacementMenus'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import type { WidgetCardMenu } from './widgetCardMenu'

export function WidgetCardMenuItems({
    menu,
    widgetItems,
}: {
    menu: WidgetCardMenu
    widgetItems: JSX.Element | null
}): JSX.Element {
    const { viewUrl, edit, duplicate, dashboard, refresh } = menu

    return (
        <>
            {widgetItems}
            {viewUrl && (
                <LemonButton to={viewUrl} fullWidth>
                    View
                </LemonButton>
            )}
            {edit && (
                <LemonButton fullWidth data-attr="dashboard-widget-edit" onClick={edit}>
                    Edit
                </LemonButton>
            )}
            {duplicate && (
                <LemonButton fullWidth onClick={duplicate}>
                    Duplicate
                </LemonButton>
            )}
            {dashboard && (
                <>
                    <LemonDivider />
                    <h5 className="mx-2 my-1">Dashboard</h5>
                    {dashboard.description && (
                        <LemonButton fullWidth onClick={dashboard.description.onClick}>
                            {dashboard.description.label}
                        </LemonButton>
                    )}
                    {dashboard.placement && (
                        <DashboardWidgetPlacementMenus
                            placementDestinations={dashboard.placement.destinations}
                            onMoveToDashboard={dashboard.placement.onMoveToDashboard}
                            onCopyToDashboard={dashboard.placement.onCopyToDashboard}
                            tileGroupMoveOptions={dashboard.placement.tileGroupMoveOptions}
                            onMoveToTileGroup={dashboard.placement.onMoveToTileGroup}
                        />
                    )}
                    {dashboard.remove && (
                        <LemonButton status="danger" fullWidth onClick={dashboard.remove}>
                            Remove from dashboard
                        </LemonButton>
                    )}
                </>
            )}
            {refresh && (
                <>
                    <LemonDivider />
                    <DashboardTileRefreshDataButton
                        onRefresh={refresh.onRefresh}
                        disabledReason={refresh.disabledReason}
                        lastRefresh={refresh.lastRefresh}
                    />
                </>
            )}
        </>
    )
}
