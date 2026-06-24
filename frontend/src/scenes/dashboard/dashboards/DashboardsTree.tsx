import './DashboardsTree.scss'

import { useActions, useValues } from 'kea'

import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType } from '~/types'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import { FolderTreeNode } from './dashboardsFileSystemUtils'
import { DashboardsTable } from './DashboardsTable'
import { NewFolderButton } from './NewFolderButton'

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

function collectPaths(nodes: FolderTreeNode[], acc: string[] = []): string[] {
    for (const node of nodes) {
        acc.push(node.path)
        collectPaths(node.children, acc)
    }
    return acc
}

// Tree arm (variant=tree): the sidebar's LemonTree as a persistent folder panel on the left, beside the
// familiar dashboards table on the right scoped to everything at or below the selected folder (root = all).
// Expansion is controlled (like the sidebar): folders are expanded by default — expandedItemIds is "every
// folder minus the ones the user collapsed" — and both the chevron (onSetExpandedItemIds) and a folder-row
// click (onFolderClick) toggle that state, so collapsing sticks and the open/close animation plays. A
// folder click also selects it, scoping the table. The table's Folder column reads the same entryByRef the
// scoping uses, so the displayed folder always matches where the dashboard actually is.
export function DashboardsTree(): JSX.Element {
    const { folderTree, currentFolder, currentSubtreeDashboards, entryByRef, collapsedFolders } =
        useValues(dashboardsFileSystemLogic)
    const { navigateToFolder, toggleFolder } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    const treeData: TreeDataItem[] = [
        {
            id: ROOT_ID,
            name: 'All dashboards',
            record: { type: 'folder', path: '' },
            children: toTreeData(folderTree),
        },
    ]

    // Every folder id (root included). Expanded = all of these except the ones explicitly collapsed, so
    // the tree opens fully by default and newly-loaded folders come in expanded.
    const allFolderIds = [ROOT_ID, ...collectPaths(folderTree)]
    const expandedItemIds = allFolderIds.filter((id) => !collapsedFolders[id])

    const folderForDashboard = (dashboard: DashboardBasicType): string => {
        const entry = entryByRef[String(dashboard.id)]
        const segments = entry?.path ? splitPath(entry.path).slice(0, -1) : []
        return segments.length > 0 ? joinPath(segments) : 'Unfiled'
    }

    return (
        <div className="grid grid-cols-[260px_1fr] gap-4" data-attr="dashboards-tree">
            <div className="flex flex-col gap-1 border-r border-border pr-2" aria-label="Folder tree">
                <div>
                    <NewFolderButton />
                </div>
                <LemonTree
                    className="px-0 py-1 dashboards-tree-panel"
                    data={treeData}
                    expandedItemIds={expandedItemIds}
                    onSetExpandedItemIds={(newIds) => {
                        // Keyboard expand/collapse: LemonTree hands back the full expanded set; mirror the one
                        // folder whose state changed into collapsedFolders so the controlled prop stays in sync.
                        const expanded = new Set(newIds)
                        const toggled = allFolderIds.find((id) => !collapsedFolders[id] !== expanded.has(id))
                        if (toggled) {
                            toggleFolder(toggled)
                        }
                    }}
                    defaultSelectedFolderOrNodeId={ROOT_ID}
                    // Mark only the selected folder (rendered as bold via the panel SCSS, not a background).
                    isItemActive={(item) => !!currentFolder && item.record?.path === currentFolder}
                    onFolderClick={(folder) => {
                        if (!folder) {
                            return
                        }
                        // A folder-row click both selects (scopes the table) and toggles its expansion; mirror
                        // the toggle so the controlled prop agrees with LemonTree and the collapse sticks.
                        navigateToFolder((folder.record?.path as string) ?? '')
                        toggleFolder(folder.id)
                    }}
                />
            </div>
            <div className="min-w-0" data-attr="dashboards-tree-content">
                <DashboardsTable
                    dashboards={currentSubtreeDashboards}
                    dashboardsLoading={dashboardsLoading}
                    folderForDashboard={folderForDashboard}
                />
            </div>
        </div>
    )
}
