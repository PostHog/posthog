import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { calculateMovePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { dashboardsFileSystemLogicType } from './dashboardsFileSystemLogicType'
import { buildEntryByRef, DashboardFolderGroup, groupDashboardsByFolder } from './dashboardsFileSystemUtils'
import { dashboardsLogic } from './dashboardsLogic'

const DASHBOARD_FS_PAGE_LIMIT = 500

// View state for the grid/finder arms: the dashboards-subtree folder structure (read from the same
// FileSystem rows that back the sidebar tree) plus per-folder collapse state. Writes are delegated to
// projectTreeDataLogic so the sidebar stays consistent and there is no second folder model to sync.
export const dashboardsFileSystemLogic = kea<dashboardsFileSystemLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'dashboardsFileSystemLogic']),
    connect(() => ({
        values: [dashboardsLogic, ['dashboards']],
        actions: [projectTreeDataLogic, ['moveItem']],
    })),
    actions({
        toggleFolder: (folder: string) => ({ folder }),
        moveDashboardToFolder: (dashboardId: number, folder: string) => ({ dashboardId, folder }),
    }),
    loaders({
        dashboardFileSystemEntries: [
            [] as FileSystemEntry[],
            {
                loadDashboardFileSystemEntries: async (): Promise<FileSystemEntry[]> => {
                    const response = await api.fileSystem.list({ type: 'dashboard', limit: DASHBOARD_FS_PAGE_LIMIT })
                    return response.results
                },
            },
        ],
    }),
    reducers({
        collapsedFolders: [
            {} as Record<string, boolean>,
            {
                toggleFolder: (state, { folder }) => ({ ...state, [folder]: !state[folder] }),
            },
        ],
    }),
    selectors({
        entryByRef: [
            (s) => [s.dashboardFileSystemEntries],
            (entries): Record<string, FileSystemEntry> => buildEntryByRef(entries),
        ],
        dashboardsByFolder: [
            (s) => [s.dashboards, s.entryByRef],
            (dashboards, entryByRef): DashboardFolderGroup[] => groupDashboardsByFolder(dashboards, entryByRef),
        ],
    }),
    listeners(({ values, actions }) => ({
        moveDashboardToFolder: ({ dashboardId, folder }) => {
            const entry = values.entryByRef[String(dashboardId)]
            if (!entry) {
                return
            }
            const { newPath, isValidMove } = calculateMovePath(entry, folder)
            if (isValidMove) {
                actions.moveItem(entry, newPath, true, 'dashboards-grid')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDashboardFileSystemEntries()
    }),
])
