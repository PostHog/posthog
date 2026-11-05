import { useActions } from 'kea'
import { useState } from 'react'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { dashboardsModel } from '~/models/dashboardsModel'

import {
    type DashboardTileGroupMenuActions,
    DashboardTileGroupMenuOverlay,
    hasTileGroupMenuActions,
} from './DashboardTileGroupMenuOverlay'

interface DashboardTileGroupContextMenuProps extends DashboardTileGroupMenuActions {
    className?: string
    onDoubleClick?: () => void
    children: React.ReactNode
}

export function DashboardTileGroupContextMenu({
    className,
    onDoubleClick,
    children,
    ...actions
}: DashboardTileGroupContextMenuProps): JSX.Element {
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)
    const [visible, setVisible] = useState(false)

    if (!hasTileGroupMenuActions(actions)) {
        return <span className={className}>{children}</span>
    }

    return (
        <LemonDropdown
            visible={visible}
            // Only right-click opens the menu. A left click on the header or tab keeps its own action.
            onVisibilityChange={(nextVisible) => !nextVisible && setVisible(false)}
            placement="bottom-start"
            overlay={<DashboardTileGroupMenuOverlay {...actions} />}
        >
            <span
                className={className}
                onDoubleClick={onDoubleClick}
                onContextMenu={(event) => {
                    event.preventDefault()
                    setVisible(true)
                    if (actions.onCopyToDashboard) {
                        loadDashboardsIfNeeded()
                    }
                }}
                data-attr="dashboard-tile-group-context-menu"
            >
                {children}
            </span>
        </LemonDropdown>
    )
}
