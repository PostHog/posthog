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

// Build the nested folder tree the tree arm renders in its LemonTree panel: every folder that contains a
// dashboard (plus all its ancestors), unioned with the explicit `folderPaths` (real folder rows) so empty
// folders also appear. Unfiled dashboards contribute the Unfiled subtree.
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
    // Split each path once, then shallowest-first so a node's parent always exists before it's attached.
    const sorted = [...allFolderPaths]
        .map((path) => ({ path, segments: splitPath(path) }))
        .sort((a, b) => a.segments.length - b.segments.length || a.path.localeCompare(b.path))
    for (const { path, segments } of sorted) {
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
