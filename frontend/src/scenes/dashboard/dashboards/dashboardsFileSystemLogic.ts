import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { DashboardBasicType } from '~/types'

import type { dashboardsFileSystemLogicType } from './dashboardsFileSystemLogicType'
import { buildEntryByRef, buildFolderTree, FolderTreeNode, subtreeDashboards } from './dashboardsFileSystemUtils'
import { dashboardsLogic } from './dashboardsLogic'

const DASHBOARD_FS_PAGE_LIMIT = 500

// View state for the tree arm: a folder tree built from the same FileSystem rows that back the sidebar
// (both dashboard and folder rows, so empty folders appear), the selected folder, its expand state, and the
// dashboards at or below it. Folder creation calls api.fileSystem.create then
// projectTreeDataLogic.createSavedItem so the sidebar's in-memory store stays consistent. Per-dashboard
// organizing (move / rename / delete) is handled by the reused DashboardsTable's own row actions, which go
// through the shared move path — there is no second folder model to sync.
export const dashboardsFileSystemLogic = kea<dashboardsFileSystemLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'dashboardsFileSystemLogic']),
    connect(() => ({
        values: [dashboardsLogic, ['dashboards']],
        actions: [projectTreeDataLogic, ['createSavedItem']],
    })),
    actions({
        // Tree arm: select a folder ('' = the dashboards root) and toggle its expand state in the panel.
        navigateToFolder: (folder: string) => ({ folder }),
        toggleFolder: (folder: string) => ({ folder }),
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
                        // v1 reads a single page; surplus dashboards fall back to Unfiled in the tree.
                        // Pagination is deferred — warn so the truncation is detectable rather than silent.
                        console.warn(
                            `dashboardsFileSystemLogic: hit the ${DASHBOARD_FS_PAGE_LIMIT}-entry page limit — some dashboards may appear under Unfiled.`
                        )
                    }
                    return response.results
                },
            },
        ],
        // Real folder rows, so empty folders (and ones the user creates) show up in the tree — not just
        // folders inferred from dashboard paths.
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
        // Tree arm: every dashboard at or below the selected folder, recursively (root = all). The tree is a
        // scope selector; the content pane (DashboardsTable) shows everything in scope.
        currentSubtreeDashboards: [
            (s) => [s.dashboards, s.entryByRef, s.currentFolder],
            (dashboards, entryByRef, currentFolder): DashboardBasicType[] =>
                subtreeDashboards(dashboards, entryByRef, currentFolder),
        ],
    }),
    listeners(({ values, actions }) => ({
        // A duplicate (via the table) creates a dashboard server-side; refetch so the subtree reflects it
        // (the new dashboard syncs its own FileSystem entry via FileSystemSyncMixin).
        [dashboardsModel.actionTypes.duplicateDashboardSuccess]: () => {
            actions.loadDashboardFileSystemEntries()
        },
        // A move lands as movedItem AFTER the server commit (the table's "Move to" action goes through the
        // shared move path). A dashboard move changes its own path; a folder move re-parents the dashboards
        // beneath it (and the folder rows). Other item types (insights, notebooks) don't affect this view,
        // so skip the refetch for them.
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
            // Mirror the dashboard-entries failure toast: without it, empty folders silently disappear and
            // the degraded structure looks like a genuinely flat project.
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
                // refresh our own folder rows and select the new folder.
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
