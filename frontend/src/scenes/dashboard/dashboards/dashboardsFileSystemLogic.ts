import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'

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
            ['duplicateDashboard', 'updateDashboard', 'deleteDashboard'],
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
        deleteDashboardWithConfirm: (dashboardId: number, name: string) => ({ dashboardId, name }),
        startRenaming: (dashboardId: number) => ({ dashboardId }),
        stopRenaming: true,
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
                // Reuses the canonical duplicate, so the copy inherits exactly the established Duplicate
                // behavior (no new sharing/subscription handling — see CH-03). The copy lands in its default
                // folder; auto-placing it into `folder` needs the new entry after duplication (follow-up).
                actions.duplicateDashboard({ id: item.dashboardId, name: source?.name, duplicateTiles: true })
                actions.loadDashboardFileSystemEntries()
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
        deleteDashboardWithConfirm: ({ dashboardId, name }) => {
            LemonDialog.open({
                title: `Delete ${name || 'this dashboard'}?`,
                description: 'This moves the dashboard to the trash — you can restore it from there.',
                primaryButton: {
                    status: 'danger',
                    children: 'Delete',
                    onClick: () => actions.deleteDashboard({ id: dashboardId, deleteInsights: false }),
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDashboardFileSystemEntries()
    }),
])
