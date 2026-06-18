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
