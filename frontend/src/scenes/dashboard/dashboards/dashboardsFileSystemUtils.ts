import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { DashboardBasicType } from '~/types'

// Dashboards with no folder entry live here by default (matches FileSystemSyncMixin's base folder).
export const UNFILED_DASHBOARDS_FOLDER = 'Unfiled/Dashboards'
const UNFILED_SEGMENTS = splitPath(UNFILED_DASHBOARDS_FOLDER)

export interface FolderTreeNode {
    // Full folder path, e.g. 'Marketing/Q1'.
    path: string
    // Last path segment, for display.
    label: string
    children: FolderTreeNode[]
}

// Index dashboard FileSystem rows by their `ref` (the dashboard id as a string) for O(1) lookup.
export function buildEntryByRef(entries: FileSystemEntry[]): Record<string, FileSystemEntry> {
    const byRef: Record<string, FileSystemEntry> = {}
    for (const entry of entries) {
        if (entry.type === 'dashboard' && entry.ref) {
            byRef[entry.ref] = entry
        }
    }
    return byRef
}

// Build the nested folder tree the tree arm renders: every folder that contains a dashboard (plus all its
// ancestors), unioned with the explicit `folderPaths` (real folder rows) so empty folders also appear.
// Unfiled dashboards contribute the Unfiled subtree.
export function buildFolderTree(
    dashboards: DashboardBasicType[],
    entryByRef: Record<string, FileSystemEntry>,
    folderPaths: string[] = []
): FolderTreeNode[] {
    const allFolderPaths = new Set<string>()
    const addWithAncestors = (segments: string[]): void => {
        for (let i = 1; i <= segments.length; i++) {
            allFolderPaths.add(joinPath(segments.slice(0, i)))
        }
    }
    for (const dashboard of dashboards) {
        const entry = entryByRef[String(dashboard.id)]
        const parentSegments = entry?.path ? splitPath(entry.path).slice(0, -1) : []
        addWithAncestors(parentSegments.length > 0 ? parentSegments : UNFILED_SEGMENTS)
    }
    for (const folderPath of folderPaths) {
        addWithAncestors(splitPath(folderPath))
    }

    const byPath = new Map<string, FolderTreeNode>()
    const roots: FolderTreeNode[] = []
    // Shallowest first so a node's parent always exists before the node is attached.
    const sorted = [...allFolderPaths].sort((a, b) => splitPath(a).length - splitPath(b).length || a.localeCompare(b))
    for (const path of sorted) {
        const segments = splitPath(path)
        const node: FolderTreeNode = { path, label: segments.at(-1) ?? path, children: [] }
        byPath.set(path, node)
        const parent = segments.length > 1 ? byPath.get(joinPath(segments.slice(0, -1))) : undefined
        ;(parent ? parent.children : roots).push(node)
    }

    const sortChildren = (nodes: FolderTreeNode[]): void => {
        nodes.sort((a, b) => a.label.localeCompare(b.label))
        nodes.forEach((node) => sortChildren(node.children))
    }
    sortChildren(roots)
    return roots
}

// dnd-kit ids for the grid: dashboards are draggable, folder headers are droppable. We namespace and
// round-trip the dashboard id / folder path through the id so the drag-end handler can resolve them.
const DRAG_PREFIX = 'dashboards-grid'
const DASH_PREFIX = `${DRAG_PREFIX}:dash:`
const FOLDER_PREFIX = `${DRAG_PREFIX}:folder:`

export function dashboardDraggableId(dashboardId: number): string {
    return `${DASH_PREFIX}${dashboardId}`
}

export function folderDroppableId(folder: string): string {
    return `${FOLDER_PREFIX}${folder}`
}

// Resolve a drag-end (dragged card → dropped-on folder header) to a move, or null if it isn't a
// valid card-onto-folder drop.
export function parseDashboardDragEnd(
    activeId: string | number | undefined | null,
    overId: string | number | undefined | null
): { dashboardId: number; folder: string } | null {
    if (!activeId || !overId) {
        return null
    }
    const active = String(activeId)
    const over = String(overId)
    if (!active.startsWith(DASH_PREFIX) || !over.startsWith(FOLDER_PREFIX)) {
        return null
    }
    const dashboardId = Number(active.slice(DASH_PREFIX.length))
    if (!Number.isInteger(dashboardId)) {
        return null
    }
    return { dashboardId, folder: over.slice(FOLDER_PREFIX.length) }
}

export interface FolderContents {
    // Full paths of the immediate child folders of `currentFolder`.
    subfolders: string[]
    // Dashboards filed directly in `currentFolder` (not in a subfolder).
    dashboards: DashboardBasicType[]
}

// Explorer arm: given the current folder, return its immediate subfolders and the dashboards directly in
// it. Subfolders come from each dashboard's folder path unioned with the explicit `folderPaths` (real
// folder rows), so empty folders also show up as navigable, droppable subfolders.
export function folderContents(
    dashboards: DashboardBasicType[],
    entryByRef: Record<string, FileSystemEntry>,
    currentFolder: string,
    folderPaths: string[] = []
): FolderContents {
    const currentSegments = currentFolder ? splitPath(currentFolder) : []
    const subfolders = new Set<string>()
    const directDashboards: DashboardBasicType[] = []

    const addImmediateChild = (segments: string[]): void => {
        const withinCurrent = currentSegments.every((segment, index) => segments[index] === segment)
        if (withinCurrent && segments.length > currentSegments.length) {
            subfolders.add(joinPath(segments.slice(0, currentSegments.length + 1)))
        }
    }

    for (const dashboard of dashboards) {
        const entry = entryByRef[String(dashboard.id)]
        // Parent segments of the dashboard's path in one split (no joinPath→splitPath round-trip).
        const parentSegments = entry?.path ? splitPath(entry.path).slice(0, -1) : []
        const segments = parentSegments.length > 0 ? parentSegments : UNFILED_SEGMENTS
        const withinCurrent = currentSegments.every((segment, index) => segments[index] === segment)
        if (!withinCurrent) {
            continue
        }
        if (segments.length === currentSegments.length) {
            directDashboards.push(dashboard)
        } else {
            subfolders.add(joinPath(segments.slice(0, currentSegments.length + 1)))
        }
    }

    for (const folderPath of folderPaths) {
        addImmediateChild(splitPath(folderPath))
    }

    return { subfolders: [...subfolders].sort((a, b) => a.localeCompare(b)), dashboards: directDashboards }
}

export interface FolderBreadcrumb {
    label: string
    path: string
}

// Breadcrumb from the dashboards root to `currentFolder`, each crumb carrying the path to navigate to.
export function folderBreadcrumb(currentFolder: string): FolderBreadcrumb[] {
    const crumbs: FolderBreadcrumb[] = [{ label: 'All dashboards', path: '' }]
    if (currentFolder) {
        const segments = splitPath(currentFolder)
        segments.forEach((segment, index) => {
            crumbs.push({ label: segment, path: joinPath(segments.slice(0, index + 1)) })
        })
    }
    return crumbs
}

// Display label for a folder card = its last path segment.
export function folderLabel(folder: string): string {
    return splitPath(folder).at(-1) ?? folder
}

// Sibling folders of `path` (the children of its parent), for the explorer breadcrumb's jump-to-sibling
// dropdown. A top-level path's siblings are the tree roots; returns [] if the parent isn't in the tree.
export function folderSiblings(path: string, folderTree: FolderTreeNode[]): FolderTreeNode[] {
    const segments = splitPath(path)
    let level = folderTree
    for (let depth = 1; depth < segments.length; depth++) {
        const ancestor = level.find((node) => node.path === joinPath(segments.slice(0, depth)))
        if (!ancestor) {
            return []
        }
        level = ancestor.children
    }
    return level
}

export interface CompactedSubfolder {
    // The deepest folder to navigate to (the end of a single-child chain) when the card is clicked.
    path: string
    // Compacted display label, e.g. 'Q1 / Campaigns / Email' for a pass-through chain.
    label: string
}

// Collapse a single-child pass-through chain: from `folder`, while it has exactly one subfolder and no
// direct dashboards, descend. Lets the explorer reach a buried dashboard in one click instead of one
// click per empty intermediate folder.
export function compactFolderChain(
    folder: string,
    dashboards: DashboardBasicType[],
    entryByRef: Record<string, FileSystemEntry>,
    folderPaths: string[] = []
): CompactedSubfolder {
    const labels = [folderLabel(folder)]
    let path = folder
    for (;;) {
        const { subfolders, dashboards: direct } = folderContents(dashboards, entryByRef, path, folderPaths)
        if (subfolders.length !== 1 || direct.length !== 0) {
            break
        }
        path = subfolders[0]
        labels.push(folderLabel(path))
    }
    return { path, label: labels.join(' / ') }
}

// Every dashboard at or below `currentFolder`, recursively. Root ('') returns all dashboards. The tree
// arm feeds these to the dashboards table, scoped to the selected folder's subtree.
export function subtreeDashboards(
    dashboards: DashboardBasicType[],
    entryByRef: Record<string, FileSystemEntry>,
    currentFolder: string
): DashboardBasicType[] {
    const prefix = currentFolder ? splitPath(currentFolder) : []
    return dashboards.filter((dashboard) => {
        const entry = entryByRef[String(dashboard.id)]
        const segments = entry?.path ? splitPath(entry.path).slice(0, -1) : UNFILED_SEGMENTS
        return prefix.every((segment, index) => segments[index] === segment)
    })
}
