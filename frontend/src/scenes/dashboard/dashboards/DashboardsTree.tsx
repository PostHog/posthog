import { useActions, useValues } from 'kea'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { DropdownMenuGroup } from 'lib/ui/DropdownMenu/DropdownMenu'

import { joinPath } from '~/layout/panel-layout/ProjectTree/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType } from '~/types'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import { dashboardParentSegments, FolderTreeNode, UNFILED_DASHBOARDS_FOLDER } from './dashboardsFileSystemUtils'
import { DashboardsTable } from './DashboardsTable'
import { DashboardsTreeFolderMenu } from './DashboardsTreeFolderMenu'

// "All dashboards" is the single tree root; every folder nests under it. record.type 'folder' makes even
// childless folders behave as folders. The folder path doubles as the id; the root uses a sentinel id.
const ROOT_ID = '__all_dashboards__'

function toTreeData(nodes: FolderTreeNode[]): TreeDataItem[] {
    return nodes.map((node) => ({
        id: node.path,
        name: node.label,
        record: { type: 'folder', path: node.path },
        children: node.children.length > 0 ? toTreeData(node.children) : undefined,
    }))
}

// Only folders that actually contain subfolders are "expandable". A childless folder is a terminal node:
// expanding it would reveal nothing in the tree (its dashboards live in the right-hand table), so it never
// gets the open-folder icon or a chevron — you just click it to scope the table.
function collectExpandablePaths(nodes: FolderTreeNode[], acc: string[] = []): string[] {
    for (const node of nodes) {
        if (node.children.length > 0) {
            acc.push(node.path)
            collectExpandablePaths(node.children, acc)
        }
    }
    return acc
}

// Tree arm (variant=tree): the sidebar's LemonTree as a persistent folder panel on the left, beside the
// familiar dashboards table on the right scoped to everything at or below the selected folder (root = all).
// Expansion is controlled: the tree opens collapsed except for the root (so you see the top-level folders),
// and clicking a folder expands it — both the chevron and a folder-row click mirror the toggle into the
// expandedFolders reducer so collapsing sticks and the open/close animation plays. The table's Folder column
// reads the same entryByRef the scoping uses, so the displayed folder always matches where the dashboard is.
export function DashboardsTree(): JSX.Element {
    const {
        folderTree,
        currentFolder,
        currentSubtreeDashboards,
        entryByRef,
        expandedFolders,
        folderEntryByPath,
        folderDashboardCounts,
    } = useValues(dashboardsFileSystemLogic)
    const { navigateToFolder, toggleFolder, setExpandedFolders } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    const treeData: TreeDataItem[] = [
        {
            id: ROOT_ID,
            name: 'All dashboards',
            record: { type: 'folder', path: '' },
            children: toTreeData(folderTree),
        },
    ]

    // The root is always open; folders with subfolders are closed until expanded. Childless folders are never
    // expandable, so they stay closed-icon terminal nodes.
    const expandablePaths = collectExpandablePaths(folderTree)
    const expandedItemIds = [ROOT_ID, ...expandablePaths.filter((id) => expandedFolders[id])]
    const allExpanded = expandablePaths.length > 0 && expandablePaths.every((id) => expandedFolders[id])

    const folderForDashboard = (dashboard: DashboardBasicType): string => {
        // Match the tree's bucketing exactly: entry-less dashboards live under Unfiled/Dashboards there,
        // so label them the same here rather than a bare "Unfiled".
        const segments = dashboardParentSegments(entryByRef[String(dashboard.id)])
        return segments.length > 0 ? joinPath(segments) : UNFILED_DASHBOARDS_FOLDER
    }

    return (
        <div className="grid grid-cols-[260px_1fr] gap-4" data-attr="dashboards-tree">
            <div className="flex flex-col border-r border-border pr-2" aria-label="Folder tree">
                {/* LemonTree drops its own className, so the override lives on this wrapper instead. Every
                    open/expanded accordion trigger is shaded with the tertiary-active fill, which made all
                    expanded folders look selected; null that fill out via the CSS variable (cascades to all
                    rows) and re-apply it only to the actively-selected folder. */}
                <div className="dashboards-tree-panel flex-1 min-h-0 [--color-bg-fill-button-tertiary-active:transparent] [&_.button-primitive--active]:!bg-[var(--color-bg-fill-highlight-50)]">
                    <LemonTree
                        data={treeData}
                        expandedItemIds={expandedItemIds}
                        // Highlight only the folder you're in; navigating moves it (and clears the rest).
                        isItemActive={(item) => item.record?.path === currentFolder}
                        renderItem={(item, children) => {
                            if (item.record?.type !== 'folder') {
                                return children
                            }
                            // The root carries the expand/collapse-all toggle as a hover button (frees the
                            // panel header); every other folder shows a trailing subtree dashboard count.
                            if (item.id === ROOT_ID && expandablePaths.length > 0) {
                                return (
                                    <span className="flex items-center gap-1 w-full min-w-0">
                                        <span className="truncate">{children}</span>
                                        <LemonButton
                                            size="small"
                                            icon={allExpanded ? <IconCollapse /> : <IconExpand />}
                                            tooltip={allExpanded ? 'Collapse all folders' : 'Expand all folders'}
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                setExpandedFolders(
                                                    allExpanded
                                                        ? {}
                                                        : Object.fromEntries(expandablePaths.map((id) => [id, true]))
                                                )
                                            }}
                                            className="ml-auto shrink-0 opacity-0 group-hover/lemon-tree-button:opacity-100"
                                            data-attr="dashboards-tree-expand-toggle"
                                        />
                                    </span>
                                )
                            }
                            const count = folderDashboardCounts[(item.record?.path as string) ?? ''] ?? 0
                            return (
                                <span className="flex items-center gap-1 w-full min-w-0">
                                    <span className="truncate">{children}</span>
                                    {count > 0 && (
                                        <span className="ml-auto shrink-0 text-xxs text-tertiary tabular-nums">
                                            {count}
                                        </span>
                                    )}
                                </span>
                            )
                        }}
                        onSetExpandedItemIds={(newIds) => {
                            // Keyboard expand/collapse: mirror the one folder whose state changed into the
                            // reducer (the root is always open, so it's excluded from the diff).
                            const expanded = new Set(newIds)
                            const toggled = expandablePaths.find((id) => !!expandedFolders[id] !== expanded.has(id))
                            if (toggled) {
                                toggleFolder(toggled)
                            }
                        }}
                        onFolderClick={(folder) => {
                            if (!folder) {
                                return
                            }
                            // A folder click selects it (scopes the table); a folder that has subfolders also
                            // toggles expansion. The root stays open; childless folders don't expand at all.
                            navigateToFolder((folder.record?.path as string) ?? '')
                            if (folder.id !== ROOT_ID && folder.children && folder.children.length > 0) {
                                toggleFolder(folder.id)
                            }
                        }}
                        itemSideAction={(item) => {
                            // Hover ellipsis on every folder (root included). Root → New folder; a real folder
                            // → New subfolder / Rename / Move to / Delete (the last three need its FileSystem row).
                            if (item.record?.type !== 'folder') {
                                return undefined
                            }
                            const path = (item.record?.path as string) ?? ''
                            return (
                                <DropdownMenuGroup>
                                    <DashboardsTreeFolderMenu path={path} entry={folderEntryByPath[path]} />
                                </DropdownMenuGroup>
                            )
                        }}
                    />
                </div>
            </div>
            <div className="min-w-0" data-attr="dashboards-tree-content">
                <DashboardsTable
                    dashboards={currentSubtreeDashboards}
                    dashboardsLoading={dashboardsLoading}
                    folderForDashboard={folderForDashboard}
                    dashboardFsEntry={(dashboard) => entryByRef[String(dashboard.id)]}
                />
            </div>
        </div>
    )
}
