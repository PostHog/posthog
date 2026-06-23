import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { calculateMovePath, joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { dashboardsFileSystemLogicType } from './dashboardsFileSystemLogicType'
import {
    buildEntryByRef,
    buildFolderTree,
    compactFolderChain,
    CompactedSubfolder,
    folderBreadcrumb,
    FolderBreadcrumb,
    folderContents,
    FolderContents,
    folderSiblings,
    FolderTreeNode,
} from './dashboardsFileSystemUtils'
import { dashboardsLogic } from './dashboardsLogic'

const DASHBOARD_FS_PAGE_LIMIT = 500
// Opaque per-caller tag for projectTreeDataLogic's move queue (distinct from the dnd-kit DRAG_PREFIX).
const DASHBOARDS_FS_LOGIC_KEY = 'dashboards-file-system'

export interface ClipboardItem {
    mode: 'cut' | 'copy'
    dashboardId: number
}

// View state for the explorer arm: the dashboards-subtree folder structure (read from the same FileSystem
// rows that back the sidebar tree — both dashboard and folder rows), folder navigation state, and a
// clipboard. Writes delegate to projectTreeDataLogic (moves) and dashboardsModel (duplicate/rename/delete);
// folder creation calls api.fileSystem.create then projectTreeDataLogic.createSavedItem so the sidebar's
// in-memory store stays consistent — there is no second folder model to sync.
export const dashboardsFileSystemLogic = kea<dashboardsFileSystemLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'dashboardsFileSystemLogic']),
    connect(() => ({
        values: [dashboardsLogic, ['dashboards']],
        actions: [
            projectTreeDataLogic,
            ['moveItem', 'createSavedItem'],
            dashboardsModel,
            ['duplicateDashboard', 'updateDashboard'],
            deleteDashboardLogic,
            ['showDeleteDashboardModal'],
        ],
    })),
    actions({
        moveDashboardToFolder: (dashboardId: number, folder: string) => ({ dashboardId, folder }),
        // Explorer arm: drill into / breadcrumb back to a folder ('' = the dashboards root).
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
        // Create a folder inside the current folder (the UI prompts for the name).
        createFolder: (name: string) => ({ name }),
    }),
    loaders({
        dashboardFileSystemEntries: [
            [] as FileSystemEntry[],
            {
                loadDashboardFileSystemEntries: async (): Promise<FileSystemEntry[]> => {
                    const response = await api.fileSystem.list({ type: 'dashboard', limit: DASHBOARD_FS_PAGE_LIMIT })
                    if (response.results.length >= DASHBOARD_FS_PAGE_LIMIT) {
                        // v1 reads a single page; surplus dashboards fall back to Unfiled in the arms.
                        // Pagination is deferred — warn so the truncation is detectable rather than silent.
                        console.warn(
                            `dashboardsFileSystemLogic: hit the ${DASHBOARD_FS_PAGE_LIMIT}-entry page limit — some dashboards may appear under Unfiled.`
                        )
                    }
                    return response.results
                },
            },
        ],
        // Real folder rows, so empty folders (and ones the user creates) show up as navigable, droppable
        // targets — not just folders inferred from dashboard paths.
        folderEntries: [
            [] as FileSystemEntry[],
            {
                loadFolderEntries: async (): Promise<FileSystemEntry[]> => {
                    const response = await api.fileSystem.list({ type: 'folder', limit: DASHBOARD_FS_PAGE_LIMIT })
                    if (response.results.length >= DASHBOARD_FS_PAGE_LIMIT) {
                        // Same single-page cap as the dashboard loader; warn so truncation is detectable.
                        console.warn(
                            `dashboardsFileSystemLogic: hit the ${DASHBOARD_FS_PAGE_LIMIT}-entry folder page limit — some folders may not appear.`
                        )
                    }
                    return response.results
                },
            },
        ],
    }),
    reducers({
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
        folderPaths: [(s) => [s.folderEntries], (folderEntries): string[] => folderEntries.map((entry) => entry.path)],
        folderTree: [
            (s) => [s.dashboards, s.entryByRef, s.folderPaths],
            (dashboards, entryByRef, folderPaths): FolderTreeNode[] =>
                buildFolderTree(dashboards, entryByRef, folderPaths),
        ],
        currentFolderContents: [
            (s) => [s.dashboards, s.entryByRef, s.currentFolder, s.folderPaths],
            (dashboards, entryByRef, currentFolder, folderPaths): FolderContents =>
                folderContents(dashboards, entryByRef, currentFolder, folderPaths),
        ],
        // Explorer arm: immediate subfolders with single-child pass-through chains collapsed, so one
        // click reaches a buried dashboard.
        compactedSubfolders: [
            (s) => [s.currentFolderContents, s.dashboards, s.entryByRef, s.folderPaths],
            (currentFolderContents, dashboards, entryByRef, folderPaths): CompactedSubfolder[] =>
                currentFolderContents.subfolders.map((subfolder) =>
                    compactFolderChain(subfolder, dashboards, entryByRef, folderPaths)
                ),
        ],
        breadcrumb: [(s) => [s.currentFolder], (currentFolder): FolderBreadcrumb[] => folderBreadcrumb(currentFolder)],
        // Explorer breadcrumb crumbs paired with their sibling folders, for the jump-to-sibling dropdowns.
        // Derived here (not in render) so the tree walk memoizes on [breadcrumb, folderTree] rather than
        // re-running per crumb on every explorer re-render. The root crumb has no siblings.
        breadcrumbWithSiblings: [
            (s) => [s.breadcrumb, s.folderTree],
            (breadcrumb, folderTree): (FolderBreadcrumb & { siblings: FolderTreeNode[] })[] =>
                breadcrumb.map((crumb, index) => ({
                    ...crumb,
                    siblings: index > 0 ? folderSiblings(crumb.path, folderTree) : [],
                })),
        ],
    }),
    listeners(({ values, actions }) => ({
        moveDashboardToFolder: ({ dashboardId, folder }) => {
            const entry = values.entryByRef[String(dashboardId)]
            if (!entry) {
                // No FileSystem row for this dashboard. Stay quiet while entries are still loading (the
                // drag landed before the fetch returned); otherwise surface it rather than no-op silently.
                if (!values.dashboardFileSystemEntriesLoading) {
                    lemonToast.warning("Could not move this dashboard — it doesn't have a folder entry yet.")
                }
                return
            }
            const { newPath, isValidMove } = calculateMovePath(entry, folder)
            if (isValidMove) {
                actions.moveItem(entry, newPath, true, DASHBOARDS_FS_LOGIC_KEY)
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
        // A move lands as movedItem AFTER the server commit. A dashboard move changes its own path; a
        // folder move re-parents the dashboards beneath it (and the folder rows). Either needs the
        // dashboard entries; only a folder move needs the folder rows. Other item types (insights,
        // notebooks) don't affect this view, so skip the refetch for them.
        [projectTreeDataLogic.actionTypes.movedItem]: ({ item }) => {
            if (item.type === 'dashboard' || item.type === 'folder') {
                actions.loadDashboardFileSystemEntries()
            }
            if (item.type === 'folder') {
                actions.loadFolderEntries()
            }
        },
        loadDashboardFileSystemEntriesFailure: () => {
            // Without this the folder structure silently collapses to Unfiled (kea-loaders only
            // console.errors), so the degraded state would look like a genuinely flat project.
            lemonToast.error('Could not load dashboard folders — they may appear unorganized. Refresh to retry.')
        },
        loadFolderEntriesFailure: () => {
            // Mirror the dashboard-entries failure toast: without it, empty folders silently disappear
            // and the degraded structure looks like a genuinely flat project.
            lemonToast.error('Could not load folders — empty folders may not appear. Refresh to retry.')
        },
        createFolder: async ({ name }) => {
            const trimmed = name.trim()
            if (!trimmed) {
                return
            }
            const path = joinPath([...(values.currentFolder ? splitPath(values.currentFolder) : []), trimmed])
            try {
                const created = await api.fileSystem.create({ type: 'folder', path } as FileSystemEntry)
                // Sync the sidebar's shared store the same way the project-tree create path does, then
                // refresh our own folder rows and drill into the new folder.
                actions.createSavedItem(created)
                actions.loadFolderEntries()
                actions.navigateToFolder(path)
                lemonToast.success(`Created folder "${trimmed}"`)
            } catch {
                lemonToast.error('Could not create the folder.')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDashboardFileSystemEntries()
        actions.loadFolderEntries()
    }),
])
