import { useActions } from 'kea'

import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from '@posthog/quill'

import { dashboardsModel } from '~/models/dashboardsModel'

import { type DashboardTileGroupMenuActions, hasTileGroupMenuActions } from './DashboardTileGroupMenuOverlay'
import { QuillDashboardTileGroupMenuItems } from './QuillDashboardTileGroupMenuItems'

interface QuillDashboardTileGroupContextMenuProps extends DashboardTileGroupMenuActions {
    className?: string
    onDoubleClick?: () => void
    children: React.ReactNode
}

export function QuillDashboardTileGroupContextMenu({
    className,
    onDoubleClick,
    children,
    ...actions
}: QuillDashboardTileGroupContextMenuProps): JSX.Element {
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)

    if (!hasTileGroupMenuActions(actions)) {
        return <span className={className}>{children}</span>
    }

    return (
        <ContextMenu onOpenChange={(open) => open && actions.onCopyToDashboard && loadDashboardsIfNeeded()}>
            <ContextMenuTrigger
                render={
                    <span
                        className={className}
                        onDoubleClick={onDoubleClick}
                        data-attr="dashboard-tile-group-context-menu"
                    />
                }
            >
                {children}
            </ContextMenuTrigger>
            <ContextMenuContent className="min-w-48">
                <QuillDashboardTileGroupMenuItems {...actions} />
            </ContextMenuContent>
        </ContextMenu>
    )
}
