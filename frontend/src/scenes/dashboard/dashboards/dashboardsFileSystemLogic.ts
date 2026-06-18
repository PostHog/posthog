import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { calculateMovePath } from '~/layout/panel-layout/ProjectTree/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { dashboardsFileSystemLogicType } from './dashboardsFileSystemLogicType'
import {
    buildEntryByRef,
    DashboardFolderGroup,
    folderBreadcrumb,
    FolderBreadcrumb,
    folderContents,
    FolderContents,
    groupDashboardsByFolder,
} from './dashboardsFileSystemUtils'
import { dashboardsLogic } from './dashboardsLogic'

const DASHBOARD_FS_PAGE_LIMIT = 500

export interface ClipboardItem {
    mode: 'cut' | 'copy'
    dashboardId: number
}

// View state for the grid/finder arms: the dashboards-subtree folder structure (read from the same
// FileSystem rows that back the sidebar tree), folder navigation/collapse state, and a clipboard. Writes
// delegate to projectTreeDataLogic (moves) and dashboardsModel (duplicate/rename/delete) so the sidebar
// stays consistent and there is no second folder model to sync.
export const dashboardsFileSystemLogic = kea<dashboardsFileSystemLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'dashboardsFileSystemLogic']),
    connect(() => ({
        values: [dashboardsLogic, ['dashboards']],
        actions: [
            projectTreeDataLogic,
            ['moveItem'],
            dashboardsModel,
            ['duplicateDashboard', 'updateDashboard'],
            deleteDashboardLogic,
            ['showDeleteDashboardModal'],
        ],
    })),
    actions({
        toggleFolder: (folder: string) => ({ folder }),
        moveDashboardToFolder: (dashboardId: number, folder: string) => ({ dashboardId, folder }),
        // Finder arm: drill into / breadcrumb back to a folder ('' = the dashboards root).
        navigateToFolder: (folder: string) => ({ folder }),
        // Clipboard: cut = move on paste, copy = duplicate on paste.
        cutDashboard: (dashboardId: number) => ({ dashboardId }),
        copyDashboard: (dashboardId: number) => ({ dashboardId }),
        clearClipboard: true,
        pasteIntoFolder: (folder: string) => ({ folder }),
        renameDashboard: (dashboardId: number, name: string) => ({ dashboardId, name }),
        deleteDashboardWithConfirm: (dashboardId: number) => ({ dashboardId }),
        startRenaming: (dashboardId: number) => ({ dashboardId }),
        stopRenaming: true,
    }),
    loaders({
        dashboardFileSystemEntries: [
            [] as FileSystemEntry[],
            {
                loadDashboardFileSystemEntries: async (): Promise<FileSystemEntry[]> => {
                    const response = await api.fileSystem.list({ type: 'dashboard', limit: DASHBOARD_FS_PAGE_LIMIT })
                    if (response.results.length >= DASHBOARD_FS_PAGE_LIMIT) {
                        // v1 reads a single page; surplus dashboards fall back to Unfiled in the grid/finder.
                        // Pagination is deferred — warn so the truncation is detectable rather than silent.
                        console.warn(
                            `dashboardsFileSystemLogic: hit the ${DASHBOARD_FS_PAGE_LIMIT}-entry page limit — some dashboards may appear under Unfiled.`
                        )
                    }
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
        currentFolder: [
            '',
            {
                navigateToFolder: (_, { folder }) => folder,
            },
        ],
        clipboard: [
            null as ClipboardItem | null,
            {
                cutDashboard: (_, { dashboardId }) => ({ mode: 'cut', dashboardId }),
                copyDashboard: (_, { dashboardId }) => ({ mode: 'copy', dashboardId }),
                clearClipboard: () => null,
            },
        ],
        renamingDashboardId: [
            null as number | null,
            {
                startRenaming: (_, { dashboardId }) => dashboardId,
                stopRenaming: () => null,
                renameDashboard: () => null,
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
        currentFolderContents: [
            (s) => [s.dashboards, s.entryByRef, s.currentFolder],
            (dashboards, entryByRef, currentFolder): FolderContents =>
                folderContents(dashboards, entryByRef, currentFolder),
        ],
        breadcrumb: [(s) => [s.currentFolder], (currentFolder): FolderBreadcrumb[] => folderBreadcrumb(currentFolder)],
    }),
    listeners(({ values, actions }) => ({
        moveDashboardToFolder: ({ dashboardId, folder }) => {
            const entry = values.entryByRef[String(dashboardId)]
            if (!entry) {
                // A dashboard with no FileSystem row shows under Unfiled but can't be filed until its
                // entry loads — surface that instead of the drag silently doing nothing.
                lemonToast.warning('Could not move this dashboard yet — its folder entry is still loading.')
                return
            }
            const { newPath, isValidMove } = calculateMovePath(entry, folder)
            if (isValidMove) {
                actions.moveItem(entry, newPath, true, 'dashboards-grid')
            }
        },
        pasteIntoFolder: ({ folder }) => {
            const item = values.clipboard
            if (!item) {
                return
            }
            if (item.mode === 'cut') {
                actions.moveDashboardToFolder(item.dashboardId, folder)
            } else {
                const source = values.dashboards.find((dashboard) => dashboard.id === item.dashboardId)
                // Reuses the canonical duplicate so the copy inherits exactly the established Duplicate
                // behavior (no new sharing/subscription handling). Known v1 limitation: the copy lands in
                // its default (Unfiled) folder, not the paste target — placing it needs the new FileSystem
                // entry after duplication, deferred as a follow-up.
                actions.duplicateDashboard({ id: item.dashboardId, name: source?.name, duplicateTiles: true })
            }
            actions.clearClipboard()
        },
        renameDashboard: ({ dashboardId, name }) => {
            const trimmed = name.trim()
            const current = values.dashboards.find((dashboard) => dashboard.id === dashboardId)
            if (trimmed && trimmed !== current?.name) {
                actions.updateDashboard({ id: dashboardId, name: trimmed, allowUndo: true })
            }
        },
        deleteDashboardWithConfirm: ({ dashboardId }) => {
            // Reuse the canonical delete modal (already rendered in Dashboards.tsx) — it owns the
            // confirmation and the "also delete insights" choice.
            actions.showDeleteDashboardModal(dashboardId)
        },
        // A copy=duplicate paste creates a dashboard server-side; refetch the subtree once it lands so
        // the copy appears (it syncs its own FileSystem entry via FileSystemSyncMixin).
        [dashboardsModel.actionTypes.duplicateDashboardSuccess]: () => {
            actions.loadDashboardFileSystemEntries()
        },
        loadDashboardFileSystemEntriesFailure: () => {
            // Without this the folder structure silently collapses to Unfiled (kea-loaders only
            // console.errors), so the degraded state would look like a genuinely flat project.
            lemonToast.error('Could not load dashboard folders — they may appear unorganized. Refresh to retry.')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDashboardFileSystemEntries()
    }),
])
