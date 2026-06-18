import { useActions, useValues } from 'kea'

import { IconChevronRight, IconDashboard, IconFolder } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType } from '~/types'

import { DashboardCardMenu } from './DashboardCardMenu'
import { DashboardsDndContext, DraggableDashboard, DroppableFolder } from './dashboardsDnd'
import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import { folderLabel } from './dashboardsFileSystemUtils'

function FinderDashboardCard({
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
                <Link to={urls.dashboard(dashboard.id)} data-attr="dashboards-finder-card">
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

// Finder arm (variant=finder): folder-first navigation + organizing. Drill into folders via the breadcrumb,
// drag a dashboard onto a subfolder, or use the per-card menu (rename / cut / copy / delete) plus the
// clipboard paste affordance. Reuses the same FileSystem folder structure as the grid arm and sidebar tree.
export function DashboardsFinder(): JSX.Element {
    const { currentFolderContents, breadcrumb, currentFolder, clipboard, renamingDashboardId } =
        useValues(dashboardsFileSystemLogic)
    const { navigateToFolder, moveDashboardToFolder, pasteIntoFolder } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    const isEmpty = currentFolderContents.subfolders.length === 0 && currentFolderContents.dashboards.length === 0
    if (dashboardsLoading && isEmpty) {
        return <Spinner className="text-2xl" />
    }

    return (
        <DashboardsDndContext onMove={moveDashboardToFolder}>
            <div className="flex flex-col gap-4" data-attr="dashboards-finder">
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex items-center gap-1 flex-wrap" aria-label="Folder breadcrumb">
                        {breadcrumb.map((crumb, index) => (
                            <span key={crumb.path} className="flex items-center gap-1">
                                {index > 0 ? <IconChevronRight className="text-muted" /> : null}
                                <button
                                    type="button"
                                    className="font-medium"
                                    onClick={() => navigateToFolder(crumb.path)}
                                >
                                    {crumb.label}
                                </button>
                            </span>
                        ))}
                    </div>
                    {clipboard ? (
                        <LemonButton type="secondary" size="small" onClick={() => pasteIntoFolder(currentFolder)}>
                            Paste into this folder
                        </LemonButton>
                    ) : null}
                </div>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
                    {currentFolderContents.subfolders.map((folder) => (
                        <DroppableFolder key={folder} folder={folder}>
                            <button
                                type="button"
                                className="w-full"
                                data-attr="dashboards-finder-folder"
                                onClick={() => navigateToFolder(folder)}
                            >
                                <LemonCard hoverEffect className="flex flex-col gap-1 h-full text-left">
                                    <IconFolder className="text-2xl text-muted" />
                                    <span className="font-semibold truncate">{folderLabel(folder)}</span>
                                </LemonCard>
                            </button>
                        </DroppableFolder>
                    ))}
                    {currentFolderContents.dashboards.map((dashboard) => (
                        <FinderDashboardCard
                            key={dashboard.id}
                            dashboard={dashboard}
                            isRenaming={renamingDashboardId === dashboard.id}
                        />
                    ))}
                </div>
            </div>
        </DashboardsDndContext>
    )
}
