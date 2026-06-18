import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconDashboard, IconFolder } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType } from '~/types'

import { DashboardsDndContext, DraggableDashboard, DroppableFolder } from './dashboardsDnd'
import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import { DashboardFolderGroup, folderLabel } from './dashboardsFileSystemUtils'

function DashboardCard({ dashboard }: { dashboard: DashboardBasicType }): JSX.Element {
    return (
        <DraggableDashboard dashboardId={dashboard.id}>
            <Link to={urls.dashboard(dashboard.id)} data-attr="dashboards-grid-card">
                <LemonCard hoverEffect className="flex flex-col gap-1 h-full">
                    <IconDashboard className="text-2xl text-muted" />
                    <span className="font-semibold truncate">{dashboard.name || 'Untitled'}</span>
                    {dashboard.description ? (
                        <span className="text-xs text-muted truncate">{dashboard.description}</span>
                    ) : null}
                </LemonCard>
            </Link>
        </DraggableDashboard>
    )
}

function FolderGroup({
    group,
    collapsed,
    onToggle,
}: {
    group: DashboardFolderGroup
    collapsed: boolean
    onToggle: () => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <DroppableFolder folder={group.folder}>
                <button
                    type="button"
                    className="flex items-center gap-2 text-left font-semibold p-1 w-full"
                    onClick={onToggle}
                >
                    {collapsed ? <IconChevronRight /> : <IconChevronDown />}
                    <IconFolder className="text-muted" />
                    <span>{folderLabel(group.folder)}</span>
                    <span className="text-muted font-normal">· {group.dashboards.length}</span>
                </button>
            </DroppableFolder>
            {!collapsed ? (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
                    {group.dashboards.map((dashboard) => (
                        <DashboardCard key={dashboard.id} dashboard={dashboard} />
                    ))}
                </div>
            ) : null}
        </div>
    )
}

// Grid arm (variant=grid): dashboards as cards grouped under collapsible folder headers, reusing the
// same folder structure the sidebar tree shows. Drag a card onto a folder header to file it (the move
// delegates to projectTreeDataLogic). No drill-in navigation or clipboard — that's the finder arm.
export function DashboardsGrid(): JSX.Element {
    const { dashboardsByFolder, collapsedFolders } = useValues(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { moveDashboardToFolder, toggleFolder } = useActions(dashboardsFileSystemLogic)

    if (dashboardsLoading && dashboardsByFolder.length === 0) {
        return <Spinner className="text-2xl" />
    }

    return (
        <DashboardsDndContext onMove={moveDashboardToFolder}>
            <div className="flex flex-col gap-6" data-attr="dashboards-grid">
                {dashboardsByFolder.map((group) => (
                    <FolderGroup
                        key={group.folder}
                        group={group}
                        collapsed={!!collapsedFolders[group.folder]}
                        onToggle={() => toggleFolder(group.folder)}
                    />
                ))}
            </div>
        </DashboardsDndContext>
    )
}
