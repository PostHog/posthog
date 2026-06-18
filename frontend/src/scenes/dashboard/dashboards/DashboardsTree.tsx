import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconFolder } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { dashboardsModel } from '~/models/dashboardsModel'

import { DashboardsTable } from './DashboardsTable'
import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import { FolderTreeNode } from './dashboardsFileSystemUtils'

interface TreeNodeProps {
    node: FolderTreeNode
    depth: number
    currentFolder: string
    collapsedFolders: Record<string, boolean>
    onNavigate: (folder: string) => void
    onToggle: (folder: string) => void
}

// Recursive folder row. State is read once in DashboardsTree and passed down, so the tree doesn't open
// one logic subscription per node.
function TreeNode({ node, depth, currentFolder, collapsedFolders, onNavigate, onToggle }: TreeNodeProps): JSX.Element {
    const collapsed = !!collapsedFolders[node.path]
    const hasChildren = node.children.length > 0
    const isCurrent = currentFolder === node.path

    return (
        <div>
            <div
                className={cn('flex items-center gap-1 rounded', isCurrent && 'bg-accent-highlight-secondary')}
                style={{ paddingLeft: `${depth * 16}px` }}
            >
                <button
                    type="button"
                    className="flex items-center justify-center w-4 shrink-0"
                    aria-label={hasChildren ? (collapsed ? 'Expand folder' : 'Collapse folder') : undefined}
                    onClick={() => hasChildren && onToggle(node.path)}
                >
                    {hasChildren ? collapsed ? <IconChevronRight /> : <IconChevronDown /> : null}
                </button>
                <button
                    type="button"
                    className="flex items-center gap-1 flex-1 text-left py-1 min-w-0"
                    data-attr="dashboards-tree-folder"
                    onClick={() => onNavigate(node.path)}
                >
                    <IconFolder className="text-muted shrink-0" />
                    <span className={cn('truncate', isCurrent && 'font-semibold')}>{node.label}</span>
                </button>
            </div>
            {hasChildren && !collapsed ? (
                <div>
                    {node.children.map((child) => (
                        <TreeNode
                            key={child.path}
                            node={child}
                            depth={depth + 1}
                            currentFolder={currentFolder}
                            collapsedFolders={collapsedFolders}
                            onNavigate={onNavigate}
                            onToggle={onToggle}
                        />
                    ))}
                </div>
            ) : null}
        </div>
    )
}

// Tree arm (variant=tree): a persistent folder tree on the left (full hierarchy, one click to any folder)
// beside the familiar dashboards table on the right, scoped to everything at or below the selected folder
// (root = all). The table brings its own row actions (move to folder, rename, delete, pin), so organizing
// happens there. Shares the FileSystem folder structure with the explorer arm and sidebar.
export function DashboardsTree(): JSX.Element {
    const { folderTree, currentFolder, currentSubtreeDashboards, collapsedFolders } =
        useValues(dashboardsFileSystemLogic)
    const { navigateToFolder, toggleFolder } = useActions(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    return (
        <div className="grid grid-cols-[240px_1fr] gap-4" data-attr="dashboards-tree">
            <div className="flex flex-col gap-0.5 border-r border-border pr-2" aria-label="Folder tree">
                <button
                    type="button"
                    className={cn(
                        'flex items-center gap-1 py-1 w-full text-left rounded',
                        currentFolder === '' && 'font-semibold bg-accent-highlight-secondary'
                    )}
                    onClick={() => navigateToFolder('')}
                >
                    <IconFolder className="text-muted shrink-0" />
                    All dashboards
                </button>
                {folderTree.map((node) => (
                    <TreeNode
                        key={node.path}
                        node={node}
                        depth={0}
                        currentFolder={currentFolder}
                        collapsedFolders={collapsedFolders}
                        onNavigate={navigateToFolder}
                        onToggle={toggleFolder}
                    />
                ))}
            </div>
            <div className="min-w-0" data-attr="dashboards-tree-content">
                <DashboardsTable dashboards={currentSubtreeDashboards} dashboardsLoading={dashboardsLoading} />
            </div>
        </div>
    )
}
