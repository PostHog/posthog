import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { withTimeout } from 'lib/utils/async'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { DashboardBasicType } from '~/types'

import type { dashboardsFileSystemLogicType } from './dashboardsFileSystemLogicType'
import {
    buildEntryByRef,
    buildFolderDashboardCounts,
    buildFolderTree,
    FolderTreeNode,
    subtreeDashboards,
} from './dashboardsFileSystemUtils'

const FILE_SYSTEM_PAGE_SIZE = 500
// Safety ceiling so a misbehaving endpoint can't loop forever — 10 pages = 5k entries, well above any realistic
// single project (and far cheaper to load than the old 40-page cap).
const MAX_FILE_SYSTEM_PAGES = 10
// Per-page timeout so one hung request can't leave the tree loader pending forever (mirrors the sidebar's
// shortcuts loader); the abort signal cancels the in-flight request on timeout.
const FILE_SYSTEM_PAGE_TIMEOUT_MS = 10000
// Scopes projectTreeDataLogic's optional post-processing (selection clear, undo re-expand) for our reused delete
// path; safely no-ops for our unmounted instance.
const DASHBOARDS_TREE_PROJECT_LOGIC_KEY = 'dashboards-tree'

// Page through every dashboard/folder FileSystem entry so large projects render their full tree instead of
// being silently truncated to the first page — the experiment measures navigation, and big projects are
// exactly the ones the tree is meant to help.
async function fetchAllFileSystemEntries(type: 'dashboard' | 'folder'): Promise<FileSystemEntry[]> {
    const entries: FileSystemEntry[] = []
    for (let page = 0; page < MAX_FILE_SYSTEM_PAGES; page++) {
        const response = await withTimeout(
            (signal) =>
                api.fileSystem.list({
                    type,
                    limit: FILE_SYSTEM_PAGE_SIZE,
                    offset: page * FILE_SYSTEM_PAGE_SIZE,
                    signal,
                }),
            FILE_SYSTEM_PAGE_TIMEOUT_MS,
            `dashboardsFileSystemLogic: ${type} page ${page} timed out`
        )
        entries.push(...response.results)
        if (response.results.length < FILE_SYSTEM_PAGE_SIZE) {
            return entries
        }
    }
    // Hitting the ceiling means a project's tree is truncated — emit a signal (not just a console.warn) so we can
    // spot affected projects and raise the cap if real usage demands it.
    posthog.capture('dashboards tree pagination ceiling hit', {
        entry_type: type,
        entries_loaded: entries.length,
        ceiling: MAX_FILE_SYSTEM_PAGES * FILE_SYSTEM_PAGE_SIZE,
    })
    return entries
}

// View state for the tree arm: a folder tree built from the same FileSystem rows that back the sidebar
// (both dashboard and folder rows, so empty folders appear), the selected folder, its expand state, and the
// dashboards at or below it. Folder creation calls api.fileSystem.create then
// projectTreeDataLogic.createSavedItem so the sidebar's in-memory store stays consistent. Per-dashboard
// organizing (move / rename / delete) is handled by the reused DashboardsTable's own row actions, which go
// through the shared move path — there is no second folder model to sync.
export const dashboardsFileSystemLogic = kea<dashboardsFileSystemLogicType>([
    path(['products', 'dashboards', 'dashboardsFileSystemLogic']),
    connect(() => ({
        values: [dashboardsLogic, ['dashboards']],
        actions: [projectTreeDataLogic, ['createSavedItem', 'movedItem', 'deleteItem']],
    })),
    actions({
        // Tree arm: select a folder ('' = the dashboards root).
        navigateToFolder: (folder: string) => ({ folder }),
        // Toggle a folder's expand/collapse state in the panel (folders start collapsed — see expandedFolders).
        toggleFolder: (folder: string) => ({ folder }),
        // Replace the whole expanded-folders map at once (Expand all / Collapse all).
        setExpandedFolders: (folders: Record<string, boolean>) => ({ folders }),
        // Mobile-only panel toggle; desktop shows the panel unconditionally via CSS.
        toggleTreePanel: true,
        // Create a folder inside `parentPath` ('' = root; defaults to the selected folder when omitted).
        createFolder: (name: string, parentPath?: string) => ({ name, parentPath }),
        // Rename a folder — moves it to a sibling path carrying the new name (descendants re-path server-side).
        renameFolder: (entry: FileSystemEntry, newName: string) => ({ entry, newName }),
        // Delete a folder via the shared delete path (its confirmation + undo + store sync live there).
        deleteFolder: (entry: FileSystemEntry) => ({ entry }),
    }),
    loaders({
        dashboardFileSystemEntries: [
            [] as FileSystemEntry[],
            {
                loadDashboardFileSystemEntries: async (): Promise<FileSystemEntry[]> =>
                    await fetchAllFileSystemEntries('dashboard'),
            },
        ],
        // Real folder rows, so empty folders (and ones the user creates) show up in the tree — not just
        // folders inferred from dashboard paths.
        folderEntries: [
            [] as FileSystemEntry[],
            {
                loadFolderEntries: async (): Promise<FileSystemEntry[]> => await fetchAllFileSystemEntries('folder'),
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
        // Folders the user has explicitly expanded. The tree starts collapsed except for the root, so it
        // opens with just the top-level folders; clicking a folder expands it. Persisted to localStorage
        // (like the sidebar tree) so an accidental reload keeps your folders open; stale paths from since-
        // deleted folders are harmless — they're filtered against the live tree before use.
        expandedFolders: [
            {} as Record<string, boolean>,
            { persist: true },
            {
                toggleFolder: (state, { folder }) => ({ ...state, [folder]: !state[folder] }),
                setExpandedFolders: (_, { folders }) => folders,
            },
        ],
        // Not persisted, so mobile always opens with the panel collapsed and the dashboards list front and centre.
        isTreePanelExpanded: [
            false,
            {
                toggleTreePanel: (state) => !state,
            },
        ],
    }),
    selectors({
        entryByRef: [
            (s) => [s.dashboardFileSystemEntries],
            (entries): Record<string, FileSystemEntry> => buildEntryByRef(entries),
        ],
        folderPaths: [(s) => [s.folderEntries], (folderEntries): string[] => folderEntries.map((entry) => entry.path)],
        // Real folder rows keyed by path, so the folder menu can act on a folder's FileSystemEntry (needs its
        // id). Folders that exist only because a dashboard references them (no row) are absent — the menu hides
        // move/rename/delete for those and offers only "New subfolder".
        folderEntryByPath: [
            (s) => [s.folderEntries],
            (folderEntries): Record<string, FileSystemEntry> =>
                Object.fromEntries(folderEntries.map((entry) => [entry.path, entry])),
        ],
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
        // Dashboard count per folder path (subtree), for the tree's trailing count badges.
        folderDashboardCounts: [
            (s) => [s.dashboards, s.entryByRef],
            (dashboards, entryByRef): Record<string, number> => buildFolderDashboardCounts(dashboards, entryByRef),
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
        createFolder: async ({ name, parentPath }) => {
            const trimmed = name.trim()
            if (!trimmed) {
                return
            }
            const parent = parentPath ?? values.currentFolder
            const path = joinPath([...(parent ? splitPath(parent) : []), trimmed])
            try {
                const created = await api.fileSystem.create({ type: 'folder', path } as FileSystemEntry)
                // Sync the sidebar's shared store the same way the project-tree create path does, then
                // refresh our own folder rows and select the new folder.
                actions.createSavedItem(created)
                actions.loadFolderEntries()
                actions.navigateToFolder(path)
                lemonToast.success(`Created folder "${trimmed}"`)
            } catch (error) {
                console.error('Error creating folder:', error)
                // Runs in an async listener, not a kea-loader, so initKea's global onFailure never sees it —
                // capture here or we're blind to folder-create error rates (a key adoption-metric operation).
                posthog.captureException(error)
                lemonToast.error('Could not create the folder.')
            }
        },
        renameFolder: async ({ entry, newName }) => {
            const trimmed = newName.trim()
            if (!trimmed || !entry.id) {
                return
            }
            const newPath = joinPath([...splitPath(entry.path).slice(0, -1), trimmed])
            if (newPath === entry.path) {
                return
            }
            try {
                await api.fileSystem.move(entry.id, newPath)
                // movedItem syncs the sidebar's store and (via our own listener below) refetches this tree.
                actions.movedItem(entry, entry.path, newPath)
                // Re-point the scope if we were inside the renamed folder — or a descendant of it, which moves
                // with it. (deleteSavedItem falls back to root because the folder is gone; rename keeps it.)
                if (values.currentFolder === entry.path) {
                    actions.navigateToFolder(newPath)
                } else if (values.currentFolder.startsWith(`${entry.path}/`)) {
                    actions.navigateToFolder(newPath + values.currentFolder.slice(entry.path.length))
                }
                lemonToast.success(`Renamed to "${trimmed}"`)
            } catch (error) {
                console.error('Error renaming folder:', error)
                // Async listener, not a kea-loader — capture so folder-rename failures surface in error tracking.
                posthog.captureException(error)
                lemonToast.error('Could not rename the folder.')
            }
        },
        deleteFolder: ({ entry }) => {
            // Reuse the shared delete: large-folder confirmation, undo toast, and store sync all live there.
            // The follow-up refetch happens in the deleteSavedItem listener below.
            actions.deleteItem(entry, DASHBOARDS_TREE_PROJECT_LOGIC_KEY)
        },
        [projectTreeDataLogic.actionTypes.deleteSavedItem]: ({ savedItem }) => {
            // Only dashboards/folders affect this view — ignore unrelated sidebar deletes (insights, notebooks),
            // matching the movedItem listener's type-gate.
            if (savedItem.type !== 'dashboard' && savedItem.type !== 'folder') {
                return
            }
            // Deleting a folder cascades to its dashboards (soft-deleted server-side, undoable). Refetch our
            // FileSystem rows AND the dashboards list itself — without the latter the soft-deleted dashboards
            // linger in dashboardsModel and the folder looks like it didn't delete.
            actions.loadFolderEntries()
            actions.loadDashboardFileSystemEntries()
            dashboardsModel.actions.loadDashboards()
            // If the folder we were scoped to — or an ancestor of it — is gone, fall back to the root
            // rather than leaving the table pointed at a now-deleted subtree.
            if (values.currentFolder === savedItem.path || values.currentFolder.startsWith(`${savedItem.path}/`)) {
                actions.navigateToFolder('')
            }
        },
        [projectTreeDataLogic.actionTypes.restoredItems]: () => {
            // An undo-delete restored items server-side; refetch so they reappear without a page reload.
            actions.loadFolderEntries()
            actions.loadDashboardFileSystemEntries()
            dashboardsModel.actions.loadDashboards()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDashboardFileSystemEntries()
        actions.loadFolderEntries()
    }),
])
