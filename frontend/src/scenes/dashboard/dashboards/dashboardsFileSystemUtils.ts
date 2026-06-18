import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { DashboardBasicType } from '~/types'

// Dashboards with no folder entry live here by default (matches FileSystemSyncMixin's base folder).
export const UNFILED_DASHBOARDS_FOLDER = 'Unfiled/Dashboards'

export interface DashboardFolderGroup {
    folder: string
    dashboards: DashboardBasicType[]
}

// The folder a FileSystem item sits in = its path minus the trailing item name.
function parentFolder(path: string): string {
    return joinPath(splitPath(path).slice(0, -1))
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

// Group dashboards under their containing folder, preserving the incoming dashboard order within each
// group and sorting folders alphabetically. Dashboards without a folder entry fall back to Unfiled.
export function groupDashboardsByFolder(
    dashboards: DashboardBasicType[],
    entryByRef: Record<string, FileSystemEntry>
): DashboardFolderGroup[] {
    const byFolder = new Map<string, DashboardBasicType[]>()
    for (const dashboard of dashboards) {
        const entry = entryByRef[String(dashboard.id)]
        const folder = (entry?.path && parentFolder(entry.path)) || UNFILED_DASHBOARDS_FOLDER
        const group = byFolder.get(folder) ?? []
        group.push(dashboard)
        byFolder.set(folder, group)
    }
    return [...byFolder.entries()]
        .map(([folder, groupedDashboards]) => ({ folder, dashboards: groupedDashboards }))
        .sort((a, b) => a.folder.localeCompare(b.folder))
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
