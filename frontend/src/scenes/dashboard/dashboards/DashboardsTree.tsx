import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

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
// Expansion is controlled: the tree opens collapsed except for the root (so you see the top-level folders),
// and clicking a folder expands it — both the chevron and a folder-row click mirror the toggle into the
// expandedFolders reducer so collapsing sticks and the open/close animation plays. The table's Folder column
// reads the same entryByRef the scoping uses, so the displayed folder always matches where the dashboard is.
export function DashboardsTree(): JSX.Element {
    const { folderTree, currentSubtreeDashboards, entryByRef, expandedFolders } = useValues(dashboardsFileSystemLogic)
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

    // The root is always open; folders are closed until the user expands them.
    const folderPaths = collectPaths(folderTree)
    const expandedItemIds = [ROOT_ID, ...folderPaths.filter((id) => expandedFolders[id])]
    const allExpanded = folderPaths.length > 0 && folderPaths.every((id) => expandedFolders[id])

    const folderForDashboard = (dashboard: DashboardBasicType): string => {
        const entry = entryByRef[String(dashboard.id)]
        const segments = entry?.path ? splitPath(entry.path).slice(0, -1) : []
        return segments.length > 0 ? joinPath(segments) : 'Unfiled'
    }

    return (
        <div className="grid grid-cols-[260px_1fr] gap-4" data-attr="dashboards-tree">
            <div className="flex flex-col gap-1 border-r border-border pr-2" aria-label="Folder tree">
                <div className="flex items-center justify-between gap-1">
                    <NewFolderButton />
                    <LemonButton
                        size="small"
                        type="tertiary"
                        onClick={() =>
                            setExpandedFolders(
                                allExpanded ? {} : Object.fromEntries(folderPaths.map((id) => [id, true]))
                            )
                        }
                        disabledReason={folderPaths.length === 0 ? 'No folders yet' : undefined}
                    >
                        {allExpanded ? 'Collapse all' : 'Expand all'}
                    </LemonButton>
                </div>
                <LemonTree
                    // Folder rows are accordion triggers; ButtonPrimitives shades any open / expanded trigger,
                    // which in this panel makes every folder look selected. Neutralize the row background here
                    // (Tailwind so HMR picks it up, unlike a new SCSS import), keeping hover.
                    className="px-0 py-1 [&_.button-primitive]:!bg-transparent [&_.button-primitive:hover]:!bg-fill-button-tertiary-hover"
                    data={treeData}
                    expandedItemIds={expandedItemIds}
                    onSetExpandedItemIds={(newIds) => {
                        // Keyboard expand/collapse: mirror the one folder whose state changed into the reducer
                        // (the root is always open, so it's excluded from the diff).
                        const expanded = new Set(newIds)
                        const toggled = folderPaths.find((id) => !!expandedFolders[id] !== expanded.has(id))
                        if (toggled) {
                            toggleFolder(toggled)
                        }
                    }}
                    onFolderClick={(folder) => {
                        if (!folder) {
                            return
                        }
                        // A folder click selects it (scopes the table); for non-root folders it also toggles
                        // expansion. The root stays open.
                        navigateToFolder((folder.record?.path as string) ?? '')
                        if (folder.id !== ROOT_ID) {
                            toggleFolder(folder.id)
                        }
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
