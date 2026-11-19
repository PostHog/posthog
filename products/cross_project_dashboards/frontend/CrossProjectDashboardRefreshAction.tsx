import { useActions, useValues } from 'kea'

import { DashboardRefreshButton } from 'lib/components/DashboardRefreshButton/DashboardRefreshButton'
import { DashboardRefreshProgress } from 'lib/components/DashboardRefreshButton/DashboardRefreshProgress'

import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'

export function CrossProjectDashboardRefreshAction(): JSX.Element | null {
    const { tiles, tilesRefreshing, loadingTileIds } = useValues(crossProjectDashboardLogic)
    const { refreshTiles, cancelRefresh } = useActions(crossProjectDashboardLogic)

    if (tiles.length === 0) {
        return null
    }

    return (
        <>
            {tilesRefreshing && (
                <DashboardRefreshProgress completed={tiles.length - loadingTileIds.length} total={tiles.length} />
            )}
            <DashboardRefreshButton
                loading={tilesRefreshing}
                onRefresh={refreshTiles}
                onCancel={cancelRefresh}
                dataAttr="cross-project-dashboard-refresh"
                shortcutName="CrossProjectDashboardRefresh"
            />
        </>
    )
}
