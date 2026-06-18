import { useActions, useValues } from 'kea'

import { IconChevronRight, IconFolder } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dashboardsModel } from '~/models/dashboardsModel'

import { DashboardCard } from './DashboardCard'
import { DashboardsDndContext, DroppableFolder } from './dashboardsDnd'
import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

// Explorer arm (variant=explorer): drill-in folder navigation + organizing. Drill into folders via the
// breadcrumb, drag a dashboard onto a subfolder, or use the per-card menu (rename / cut / copy / delete)
// plus the clipboard paste affordance. Shares the FileSystem folder structure with the tree arm and sidebar.
export function DashboardsExplorer(): JSX.Element {
    const { currentFolderContents, compactedSubfolders, breadcrumb, currentFolder, clipboard, renamingDashboardId } =
        useValues(dashboardsFileSystemLogic)
    const { navigateToFolder, moveDashboardToFolder, pasteIntoFolder } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    const isEmpty = compactedSubfolders.length === 0 && currentFolderContents.dashboards.length === 0
    if (dashboardsLoading && isEmpty) {
        return <Spinner className="text-2xl" />
    }

    return (
        <DashboardsDndContext onMove={moveDashboardToFolder}>
            <div className="flex flex-col gap-4" data-attr="dashboards-explorer">
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
                    {compactedSubfolders.map((subfolder) => (
                        <DroppableFolder key={subfolder.path} folder={subfolder.path}>
                            <button
                                type="button"
                                className="w-full"
                                data-attr="dashboards-explorer-folder"
                                onClick={() => navigateToFolder(subfolder.path)}
                            >
                                <LemonCard hoverEffect className="flex flex-col gap-1 h-full text-left">
                                    <IconFolder className="text-2xl text-muted" />
                                    <span className="font-semibold truncate">{subfolder.label}</span>
                                </LemonCard>
                            </button>
                        </DroppableFolder>
                    ))}
                    {currentFolderContents.dashboards.map((dashboard) => (
                        <DashboardCard
                            key={dashboard.id}
                            dashboard={dashboard}
                            isRenaming={renamingDashboardId === dashboard.id}
                        />
                    ))}
                </div>
                {isEmpty ? (
                    // Empty view (the breadcrumb above still navigates back), not a dead end (EC-06b).
                    <div className="text-muted text-center py-8" data-attr="dashboards-explorer-empty">
                        This folder is empty.
                    </div>
                ) : null}
            </div>
        </DashboardsDndContext>
    )
}
