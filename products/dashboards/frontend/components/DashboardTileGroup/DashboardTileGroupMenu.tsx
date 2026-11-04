import { useActions } from 'kea'

import { More } from 'lib/lemon-ui/LemonButton/More'

import { dashboardsModel } from '~/models/dashboardsModel'

import {
    type DashboardTileGroupMenuActions,
    DashboardTileGroupMenuOverlay,
    TILE_GROUP_MENU_ITEMS,
} from './DashboardTileGroupMenuOverlay'

interface DashboardTileGroupMenuProps extends DashboardTileGroupMenuActions {
    copyLoading?: boolean
}

export function DashboardTileGroupMenu({ copyLoading, ...actions }: DashboardTileGroupMenuProps): JSX.Element {
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)
    const { copyNoun } = TILE_GROUP_MENU_ITEMS[actions.groupDisplay]

    return (
        <More
            data-attr="dashboard-tile-group-menu"
            tooltip="Group actions"
            loading={copyLoading}
            disabledReason={copyLoading ? `Copying ${copyNoun}` : undefined}
            dropdown={{
                onVisibilityChange: (visible) => visible && actions.onCopyToDashboard && loadDashboardsIfNeeded(),
            }}
            overlay={<DashboardTileGroupMenuOverlay {...actions} />}
        />
    )
}
