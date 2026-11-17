import { useActions, useValues } from 'kea'

import { DashboardRefreshButton } from 'lib/components/DashboardRefreshButton/DashboardRefreshButton'

import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'

export function CrossProjectDashboardRefreshAction(): JSX.Element | null {
    const { tiles, tilesRefreshing } = useValues(crossProjectDashboardLogic)
    const { refreshTiles } = useActions(crossProjectDashboardLogic)

    if (tiles.length === 0) {
        return null
    }

    return (
        <DashboardRefreshButton
            loading={tilesRefreshing}
            onRefresh={() => refreshTiles(tiles.map((tile) => tile.id))}
            dataAttr="cross-project-dashboard-refresh"
            shortcutName="CrossProjectDashboardRefresh"
        />
    )
}
