import { useActions } from 'kea'

import { IconDashboard } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { DashboardBasicType } from '~/types'

import { DashboardCardMenu } from './DashboardCardMenu'
import { DraggableDashboard } from './dashboardsDnd'
import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

// Dashboard card for the explorer arm: draggable onto a folder, with an inline-rename input
// (a single onBlur commit path) and the per-card actions menu.
export function DashboardCard({
    dashboard,
    isRenaming,
}: {
    dashboard: DashboardBasicType
    isRenaming: boolean
}): JSX.Element {
    const { renameDashboard, stopRenaming } = useActions(dashboardsFileSystemLogic)

    if (isRenaming) {
        return (
            <LemonCard className="flex flex-col gap-1 h-full">
                <IconDashboard className="text-2xl text-muted" />
                <input
                    autoFocus
                    defaultValue={dashboard.name || ''}
                    aria-label="Rename dashboard"
                    className="w-full bg-transparent border-b border-primary"
                    // onBlur is the single commit path. Enter blurs into it; Escape resets the value
                    // first so the unmount-blur is a no-op rename. Keeps a rename from firing twice.
                    onBlur={(e) => renameDashboard(dashboard.id, e.currentTarget.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            e.currentTarget.blur()
                        } else if (e.key === 'Escape') {
                            e.currentTarget.value = dashboard.name || ''
                            stopRenaming()
                        }
                    }}
                />
            </LemonCard>
        )
    }

    return (
        <DraggableDashboard dashboardId={dashboard.id}>
            <div className="relative">
                <Link to={urls.dashboard(dashboard.id)} data-attr="dashboards-card">
                    <LemonCard hoverEffect className="flex flex-col gap-1 h-full">
                        <IconDashboard className="text-2xl text-muted" />
                        <span className="font-semibold truncate">{dashboard.name || 'Untitled'}</span>
                    </LemonCard>
                </Link>
                <div className="absolute top-1 right-1">
                    <DashboardCardMenu dashboardId={dashboard.id} />
                </div>
            </div>
        </DraggableDashboard>
    )
}
