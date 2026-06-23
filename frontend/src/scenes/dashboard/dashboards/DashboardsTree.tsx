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

// Tree arm (variant=tree): the sidebar's LemonTree as a persistent folder panel on the left, beside the
// familiar dashboards table on the right scoped to everything at or below the selected folder (root = all).
// LemonTree owns expansion (uncontrolled, expand-all by default) so collapsing sticks; a folder click
// selects it and scopes the table. The table brings its own row actions (move / rename / delete), so
// organizing happens there. The table's Folder column reads the same entryByRef the scoping uses, so the
// displayed folder always matches where the dashboard actually is.
export function DashboardsTree(): JSX.Element {
    const { folderTree, currentFolder, currentSubtreeDashboards, entryByRef } = useValues(dashboardsFileSystemLogic)
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
                    // expandAllFolders seeds the expanded set once at mount; the folder rows load async, so
                    // re-key when they arrive to re-run it with the full tree (otherwise it renders collapsed).
                    key={folderTree.length > 0 ? 'loaded' : 'empty'}
                    className="px-0 py-1 dashboards-tree-panel"
                    data={treeData}
                    expandAllFolders
                    defaultSelectedFolderOrNodeId={ROOT_ID}
                    // Mark only the selected folder (rendered as bold via the panel SCSS, not a background).
                    isItemActive={(item) => !!currentFolder && item.record?.path === currentFolder}
                    onFolderClick={(folder) => folder && navigateToFolder((folder.record?.path as string) ?? '')}
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
