import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'

import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { cn } from 'lib/utils/css-classes'

import { dashboardsModel } from '~/models/dashboardsModel'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import { FolderTreeNode } from './dashboardsFileSystemUtils'
import { DashboardsTable } from './DashboardsTable'
import { NewFolderButton } from './NewFolderButton'

// Map our folder tree onto LemonTree's item shape. record.type 'folder' makes even childless folders
// behave as folders (so onFolderClick fires for them), and the path doubles as the unique id.
function toTreeData(nodes: FolderTreeNode[]): TreeDataItem[] {
    return nodes.map((node) => ({
        id: node.path,
        name: node.label,
        record: { type: 'folder', path: node.path },
        children: node.children.length > 0 ? toTreeData(node.children) : undefined,
    }))
}

function collectPaths(nodes: FolderTreeNode[], acc: string[] = []): string[] {
    for (const node of nodes) {
        acc.push(node.path)
        collectPaths(node.children, acc)
    }
    return acc
}

// Tree arm (variant=tree): the sidebar's LemonTree as a persistent folder panel on the left, beside the
// familiar dashboards table on the right scoped to everything at or below the selected folder (root = all).
// Expansion reuses the logic's collapsedFolders; the table brings its own row actions (move/rename/delete),
// so organizing happens there. Shares the FileSystem folder structure with the explorer arm and sidebar.
export function DashboardsTree(): JSX.Element {
    const { folderTree, currentFolder, currentSubtreeDashboards, collapsedFolders } =
        useValues(dashboardsFileSystemLogic)
    const { navigateToFolder, toggleFolder } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    const allPaths = collectPaths(folderTree)
    const expandedItemIds = allPaths.filter((path) => !collapsedFolders[path])

    return (
        <div className="grid grid-cols-[240px_1fr] gap-4" data-attr="dashboards-tree">
            <div className="flex flex-col gap-1 border-r border-border pr-2" aria-label="Folder tree">
                <div>
                    <NewFolderButton />
                </div>
                <button
                    type="button"
                    className={cn(
                        'flex items-center gap-1 py-1 px-1 w-full text-left rounded',
                        currentFolder === '' && 'font-semibold bg-accent-highlight-secondary'
                    )}
                    onClick={() => navigateToFolder('')}
                >
                    <IconFolder className="text-muted shrink-0" />
                    All dashboards
                </button>
                <LemonTree
                    data={toTreeData(folderTree)}
                    expandedItemIds={expandedItemIds}
                    onSetExpandedItemIds={(newIds) => {
                        // LemonTree hands back the full expanded set; toggle the one folder that changed.
                        const expanded = new Set(newIds)
                        const toggled = allPaths.find((path) => !collapsedFolders[path] !== expanded.has(path))
                        if (toggled) {
                            toggleFolder(toggled)
                        }
                    }}
                    isItemActive={(item) => item.record?.path === currentFolder}
                    onFolderClick={(folder) => folder && navigateToFolder((folder.record?.path as string) ?? '')}
                />
            </div>
            <div className="min-w-0" data-attr="dashboards-tree-content">
                <DashboardsTable dashboards={currentSubtreeDashboards} dashboardsLoading={dashboardsLoading} />
            </div>
        </div>
    )
}
