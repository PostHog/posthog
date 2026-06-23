import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'

import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { dashboardsModel } from '~/models/dashboardsModel'

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

// Tree arm (variant=tree): the sidebar's LemonTree as a persistent folder panel on the left, beside the
// familiar dashboards table on the right scoped to everything at or below the selected folder (root = all).
// LemonTree owns expansion (uncontrolled, expand-all by default) so collapsing sticks; a folder click
// selects it and scopes the table. The table brings its own row actions (move / rename / delete), so
// organizing happens there.
export function DashboardsTree(): JSX.Element {
    const { folderTree, currentFolder, currentSubtreeDashboards, currentSubfolders } =
        useValues(dashboardsFileSystemLogic)
    const { navigateToFolder } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    const treeData: TreeDataItem[] = [
        {
            id: ROOT_ID,
            name: 'All dashboards',
            record: { type: 'folder', path: '' },
            children: toTreeData(folderTree),
        },
    ]

    return (
        <div className="grid grid-cols-[260px_1fr] gap-4" data-attr="dashboards-tree">
            <div className="flex flex-col gap-1 border-r border-border pr-2" aria-label="Folder tree">
                <div>
                    <NewFolderButton />
                </div>
                <LemonTree
                    className="px-0 py-1"
                    data={treeData}
                    expandAllFolders
                    defaultSelectedFolderOrNodeId={ROOT_ID}
                    // Highlight only the actively-selected folder — never the whole tree. Empty at the root.
                    isItemActive={(item) => !!currentFolder && item.record?.path === currentFolder}
                    onFolderClick={(folder) => folder && navigateToFolder((folder.record?.path as string) ?? '')}
                />
            </div>
            <div className="min-w-0 flex flex-col gap-3" data-attr="dashboards-tree-content">
                {currentSubfolders.length > 0 ? (
                    // Immediate subfolders of the selected folder, so the structure stays visible while the
                    // table below lists everything in the subtree. Click one to scope down into it.
                    <div className="flex items-center gap-2 flex-wrap" aria-label="Subfolders">
                        {currentSubfolders.map((subfolder) => (
                            <button
                                key={subfolder.path}
                                type="button"
                                className="flex items-center gap-1.5 px-2 py-1 rounded border border-border hover:bg-fill-button-tertiary-hover text-sm"
                                onClick={() => navigateToFolder(subfolder.path)}
                            >
                                <IconFolder className="text-muted shrink-0" />
                                {subfolder.label}
                            </button>
                        ))}
                    </div>
                ) : null}
                <DashboardsTable dashboards={currentSubtreeDashboards} dashboardsLoading={dashboardsLoading} />
            </div>
        </div>
    )
}
