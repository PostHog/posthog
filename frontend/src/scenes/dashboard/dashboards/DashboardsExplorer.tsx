import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconFolder } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { dashboardsModel } from '~/models/dashboardsModel'

import { DashboardCard } from './DashboardCard'
import { DashboardsDndContext, DroppableFolder } from './dashboardsDnd'
import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import { DashboardsFiltersBar } from './DashboardsFiltersBar'
import { dashboardsLogic } from './dashboardsLogic'
import { NewFolderButton } from './NewFolderButton'

// Explorer arm (variant=explorer): drill-in folder navigation + organizing. Drill into folders via the
// breadcrumb, drag a dashboard onto a subfolder, or use the per-card menu (move to / rename / cut / copy /
// delete) plus the clipboard paste affordance. A search query flips to a flat global results grid. Shares
// the FileSystem folder structure (dashboard + folder rows) with the sidebar tree.
export function DashboardsExplorer(): JSX.Element {
    const {
        currentFolderContents,
        compactedSubfolders,
        breadcrumbWithSiblings,
        currentFolder,
        clipboard,
        renamingDashboardId,
        dashboardFileSystemEntriesLoading,
        folderEntriesLoading,
    } = useValues(dashboardsFileSystemLogic)
    const { navigateToFolder, moveDashboardToFolder, pasteIntoFolder } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    // The dashboards list is already filtered by the shared search/filters bar; a search query switches
    // the explorer from folder navigation to a flat list of all matches.
    const { dashboards, filters } = useValues(dashboardsLogic)
    const searching = !!filters.search?.trim()

    const isEmpty = compactedSubfolders.length === 0 && currentFolderContents.dashboards.length === 0
    // The dashboard list and the folder-structure rows load independently; hold the spinner until all
    // three settle so we don't flash "This folder is empty" when the list returns before the FS rows do.
    const loading = dashboardsLoading || dashboardFileSystemEntriesLoading || folderEntriesLoading
    if (loading && isEmpty && !searching) {
        return <Spinner className="text-2xl" />
    }

    return (
        <DashboardsDndContext onMove={moveDashboardToFolder}>
            <div className="flex flex-col gap-4" data-attr="dashboards-explorer">
                <DashboardsFiltersBar />
                {searching ? (
                    <div
                        className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3"
                        data-attr="dashboards-explorer-search-results"
                    >
                        {dashboards.map((dashboard) => (
                            <DashboardCard
                                key={dashboard.id}
                                dashboard={dashboard}
                                isRenaming={renamingDashboardId === dashboard.id}
                            />
                        ))}
                        {dashboards.length === 0 ? (
                            <div className="text-muted py-8">No dashboards match your search.</div>
                        ) : null}
                    </div>
                ) : (
                    <>
                        <div className="flex items-center gap-2 flex-wrap">
                            <div className="flex items-center gap-1 flex-wrap" aria-label="Folder breadcrumb">
                                {breadcrumbWithSiblings.map((crumb, index) => (
                                    <span key={crumb.path} className="flex items-center gap-1">
                                        {index > 0 ? <IconChevronRight className="text-muted" /> : null}
                                        <button
                                            type="button"
                                            className="font-medium"
                                            onClick={() => navigateToFolder(crumb.path)}
                                        >
                                            {crumb.label}
                                        </button>
                                        {crumb.siblings.length > 1 ? (
                                            <DropdownMenu>
                                                <DropdownMenuTrigger
                                                    render={
                                                        <Button
                                                            variant="default"
                                                            size="icon-sm"
                                                            aria-label={`Switch ${crumb.label} folder`}
                                                        />
                                                    }
                                                >
                                                    <IconChevronDown className="text-tertiary" />
                                                </DropdownMenuTrigger>
                                                <DropdownMenuContent align="start" side="bottom">
                                                    {crumb.siblings.map((sibling) => (
                                                        <DropdownMenuItem
                                                            key={sibling.path}
                                                            onClick={() => navigateToFolder(sibling.path)}
                                                        >
                                                            {sibling.label}
                                                        </DropdownMenuItem>
                                                    ))}
                                                </DropdownMenuContent>
                                            </DropdownMenu>
                                        ) : null}
                                    </span>
                                ))}
                            </div>
                            {clipboard ? (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => pasteIntoFolder(currentFolder)}
                                >
                                    Paste into this folder
                                </LemonButton>
                            ) : null}
                            <NewFolderButton />
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
                    </>
                )}
            </div>
        </DashboardsDndContext>
    )
}
