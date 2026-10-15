import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { escapePath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { todayAnalyticsLogic } from '~/layout/today/todayAnalyticsLogic'
import { fileSystemTypes } from '~/products'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { fileSystemTypeParams } from './analyticsFeed'
import {
    ANALYTICS_TYPES,
    ANALYTICS_TYPE_INFO,
    AnalyticsType,
    UNFILED_FOLDER,
    USERS_FOLDER,
    fileSystemBaseType,
    fileSystemEntryName,
    isAnalyticsType,
} from './analyticsUtils'

// Top-level folders come a page at a time; a project with more than this many is unlikely but handled.
const SPACES_PAGE_SIZE = 200
// Marks the shortcuts this page makes, so other folder shortcuts (such as a home folder) stay off the list.
// kea-localstorage keys by logic path, and starred spaces belong to one person in one project. Without
// both ids (OAuth mode can load this module early) nothing persists, so one account never sees another's.
const SHORTCUTS_TEAM_ID = getCurrentTeamIdOrNone()
const SHORTCUTS_USER_ID = getCurrentUserIdOrNone()
const SHORTCUTS_PERSIST_OPTIONS =
    SHORTCUTS_TEAM_ID && SHORTCUTS_USER_ID
        ? { persist: true, prefix: `${SHORTCUTS_TEAM_ID}__${SHORTCUTS_USER_ID}__` }
        : { persist: false }

/** A space is a top-level folder that is not the unfiled area or someone's home folder. */
export function isSpacePath(path: string): boolean {
    const segments = splitPath(path)
    return segments.length === 1 && !([UNFILED_FOLDER, USERS_FOLDER] as string[]).includes(segments[0])
}

/** A starred space: its shortcut row, so the star can be removed again. */
export interface StarredSpace {
    shortcutId: NonNullable<FileSystemEntry['id']>
    path: string
    name: string
}

export interface AnalyticsSpace {
    path: string
    name: string
    /** How many rows of each analytics type the space holds, from the API's own counts. */
    counts: Record<AnalyticsType, number>
    total: number
    /** When something was last added, from the newest row. */
    lastAddedAt: string | null
}

async function listAllTopLevelFolders(): Promise<FileSystemEntry[]> {
    const folders: FileSystemEntry[] = []
    for (let offset = 0; ; offset += SPACES_PAGE_SIZE) {
        const page = await api.fileSystem.list({ depth: 1, type: 'folder', limit: SPACES_PAGE_SIZE, offset })
        folders.push(...page.results)
        if (!page.next || page.results.length === 0) {
            return folders
        }
    }
}

// Contents move out a page at a time; a folder page is this many rows.
const EMPTY_PAGE_SIZE = 200

async function listAllFolders(parent: string): Promise<FileSystemEntry[]> {
    const folders: FileSystemEntry[] = []
    for (let offset = 0; ; offset += EMPTY_PAGE_SIZE) {
        const page = await api.fileSystem.list({ parent, type: 'folder', limit: EMPTY_PAGE_SIZE, offset })
        folders.push(...page.results.filter((entry) => entry.id))
        if (!page.next || page.results.length === 0) {
            return folders
        }
    }
}

/**
 * Moves everything out of a space back to unfiled: analytics rows to their own unfiled folder, other rows
 * to an unfiled folder named after their type. Folders stay behind empty and go with the space.
 */
export async function emptySpace(path: string): Promise<void> {
    for (;;) {
        const page = await api.fileSystem.list({ parent: path, notType: 'folder', limit: EMPTY_PAGE_SIZE })
        const rows = page.results.filter((entry) => entry.id)
        if (!rows.length) {
            return
        }
        for (const entry of rows) {
            const baseType = fileSystemBaseType(entry.type)
            const unfiled = isAnalyticsType(baseType)
                ? `${UNFILED_FOLDER}/${ANALYTICS_TYPE_INFO[baseType].pluralLabel}`
                : `${UNFILED_FOLDER}/${fileSystemTypeName(baseType)}`
            await api.fileSystem.move(entry.id!, `${unfiled}/${escapePath(fileSystemEntryName(entry))}`)
        }
        if (!page.next) {
            return
        }
    }
}

function fileSystemTypeName(type: string): string {
    const definition = Object.hasOwn(fileSystemTypes, type)
        ? (fileSystemTypes[type as keyof typeof fileSystemTypes] as { name?: string })
        : null
    return definition?.name ? `${definition.name}s` : 'Other'
}

/** One request per type reads the count and the newest row, so a big space costs four small calls. */
export async function loadSpace(folder: FileSystemEntry): Promise<AnalyticsSpace> {
    const pages = await Promise.all(
        ANALYTICS_TYPES.map((info) =>
            api.fileSystem.list({
                parent: folder.path,
                ...fileSystemTypeParams(info.type),
                orderBy: '-created_at',
                limit: 1,
            })
        )
    )
    const counts = Object.fromEntries(
        ANALYTICS_TYPES.map((info, index) => [info.type, pages[index].count ?? pages[index].results.length])
    ) as Record<AnalyticsType, number>
    const lastAddedAt = pages
        .map((page) => page.results[0]?.created_at ?? null)
        .filter((value): value is string => !!value)
        .sort()
        .at(-1)
    return {
        path: folder.path,
        name: fileSystemEntryName(folder),
        counts,
        total: Object.values(counts).reduce((sum, count) => sum + count, 0),
        lastAddedAt: lastAddedAt ?? null,
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface analyticsSpacesLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    deleteInProgress: boolean
    deletingSpace: Pick<AnalyticsSpace, 'name' | 'path'> | null
    shortcuts: FileSystemEntry[]
    shortcutsLoading: boolean
    spaces: AnalyticsSpace[]
    spacesFailed: boolean
    spacesLoading: boolean
    starredPaths: Set<string>
    starredSpaces: StarredSpace[]
    starring: string | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface analyticsSpacesLogicActions {
    folderCreated: () => {
        value: true
    } // todayAnalyticsLogic
    closeDeleteSpace: () => {
        value: true
    }
    deleteSpace: () => {
        value: true
    }
    deleteSpaceDone: (deleted: boolean) => {
        deleted: boolean
    }
    loadShortcuts: () => any
    loadShortcutsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadShortcutsSuccess: (
        shortcuts: FileSystemEntry[],
        payload?: any
    ) => {
        shortcuts: FileSystemEntry[]
        payload?: any
    }
    loadSpaces: (_: void) => void
    loadSpacesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSpacesSuccess: (
        spaces: AnalyticsSpace[],
        payload?: void
    ) => {
        spaces: AnalyticsSpace[]
        payload?: void
    }
    openDeleteSpace: (space: Pick<AnalyticsSpace, 'name' | 'path'>) => {
        space: Pick<AnalyticsSpace, 'name' | 'path'>
    }
    toggleStar: (space: Pick<AnalyticsSpace, 'name' | 'path'>) => {
        space: Pick<AnalyticsSpace, 'name' | 'path'>
    }
    toggleStarDone: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface analyticsSpacesLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        starredSpaces: (shortcuts: FileSystemEntry[]) => StarredSpace[]
        starredPaths: (starredSpaces: StarredSpace[]) => Set<string>
    }
}

export type analyticsSpacesLogicType = MakeLogicType<
    analyticsSpacesLogicValues,
    analyticsSpacesLogicActions,
    Record<string, any>,
    analyticsSpacesLogicMeta
>

/** The project's spaces: its top-level folders, with what each one holds. */
export const analyticsSpacesLogic = kea<analyticsSpacesLogicType>([
    path(['scenes', 'analytics', 'analyticsSpacesLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [todayAnalyticsLogic, ['folderCreated']],
    })),
    actions({
        toggleStar: (space: Pick<AnalyticsSpace, 'path' | 'name'>) => ({ space }),
        toggleStarDone: true,
        openDeleteSpace: (space: Pick<AnalyticsSpace, 'path' | 'name'>) => ({ space }),
        closeDeleteSpace: true,
        /** Sends everything in the space back to unfiled, then removes the space. */
        deleteSpace: true,
        deleteSpaceDone: (deleted: boolean) => ({ deleted }),
    }),
    loaders(({ cache }) => ({
        shortcuts: [
            [] as FileSystemEntry[],
            {
                loadShortcuts: async () => (await api.fileSystemShortcuts.list()).results,
            },
        ],
        spaces: [
            [] as AnalyticsSpace[],
            {
                loadSpaces: async (_: void, breakpoint) => {
                    const folders = await listAllTopLevelFolders()
                    breakpoint()
                    const spaces = await Promise.all(
                        folders
                            .filter((folder) => ![UNFILED_FOLDER, USERS_FOLDER].includes(fileSystemEntryName(folder)))
                            .map(loadSpace)
                    )
                    breakpoint()
                    cache.loaded = true
                    return spaces.sort((first, second) => first.name.localeCompare(second.name))
                },
            },
        ],
    })),
    reducers({
        spacesFailed: [
            false,
            { loadSpaces: () => false, loadSpacesSuccess: () => false, loadSpacesFailure: () => true },
        ],
        // The last loaded shortcuts persist, so starred spaces show at once on the next visit and refresh in place.
        shortcuts: [[] as FileSystemEntry[], SHORTCUTS_PERSIST_OPTIONS, {}],
        // The path being starred or unstarred, so its button shows progress and ignores a second click.
        starring: [null as string | null, { toggleStar: (_, { space }) => space.path, toggleStarDone: () => null }],
        deletingSpace: [
            null as Pick<AnalyticsSpace, 'path' | 'name'> | null,
            {
                openDeleteSpace: (_, { space }) => space,
                closeDeleteSpace: () => null,
                deleteSpaceDone: (state, { deleted }) => (deleted ? null : state),
            },
        ],
        deleteInProgress: [
            false,
            { deleteSpace: () => true, deleteSpaceDone: () => false, closeDeleteSpace: () => false },
        ],
    }),
    selectors({
        // A starred space is a shortcut to its folder; the shortcut row carries the path.
        starredSpaces: [
            (s) => [s.shortcuts],
            (shortcuts: FileSystemEntry[]): StarredSpace[] =>
                shortcuts.flatMap((shortcut) =>
                    shortcut.type === 'folder' && shortcut.id && isSpacePath(shortcut.path)
                        ? [{ shortcutId: shortcut.id, path: shortcut.path, name: fileSystemEntryName(shortcut) }]
                        : []
                ),
        ],
        starredPaths: [
            (s) => [s.starredSpaces],
            (starredSpaces: StarredSpace[]): Set<string> => new Set(starredSpaces.map((space) => space.path)),
        ],
    }),
    listeners(({ actions, values }) => ({
        toggleStar: async ({ space }) => {
            try {
                const starred = values.starredSpaces.find((candidate) => candidate.path === space.path)
                if (starred) {
                    await api.fileSystemShortcuts.delete(starred.shortcutId)
                    lemonToast.success(`Removed ${space.name} from your sidebar`)
                } else {
                    // A folder shortcut keeps its path as ref, so a rename moves the star with the folder.
                    await api.fileSystemShortcuts.create({ path: space.path, type: 'folder', ref: space.path })
                    lemonToast.success(`Added ${space.name} to your sidebar`)
                }
                actions.loadShortcuts()
            } catch {
                lemonToast.error('Could not update the star.')
            }
            actions.toggleStarDone()
        },
    })),
    listeners(({ actions, values, cache }) => ({
        // Flags can arrive after the mount, so a mount that skipped the load must load now.
        [featureFlagLogic.actionTypes.setFeatureFlags]: () => {
            if (!values.featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] || cache.flagSeen) {
                return
            }
            cache.flagSeen = true
            actions.loadShortcuts()
            if (removeProjectIdIfPresent(router.values.location.pathname) === urls.analyticsSpaces()) {
                actions.loadSpaces()
            }
        },
        // A space made from the dialog shows up without a reload.
        folderCreated: () => {
            if (removeProjectIdIfPresent(router.values.location.pathname) === urls.analyticsSpaces()) {
                actions.loadSpaces()
            }
        },
        deleteSpace: async () => {
            const space = values.deletingSpace
            if (!space) {
                return
            }
            try {
                const folder = (await api.fileSystem.list({ path: space.path, type: 'folder', limit: 1 })).results[0]
                if (!folder?.id) {
                    throw new Error('This space has no folder row.')
                }
                await emptySpace(space.path)
                const left = await api.fileSystem.list({ parent: space.path, notType: 'folder', limit: 1 })
                if ((left.count ?? left.results.length) > 0) {
                    throw new Error('Some items could not be moved, so the space stays.')
                }
                // Only empty folders remain, deepest first. Each delete is non-recursive, so the server
                // refuses if anything slipped in meanwhile.
                const folders = await listAllFolders(space.path)
                for (const child of folders.sort(
                    (first, second) => splitPath(second.path).length - splitPath(first.path).length
                )) {
                    await api.fileSystem.delete(child.id!, { recursive: false })
                }
                await api.fileSystem.delete(folder.id, { recursive: false })
                const star = values.starredSpaces.find((candidate) => candidate.path === space.path)
                if (star) {
                    await api.fileSystemShortcuts.delete(star.shortcutId)
                }
                lemonToast.success(`Deleted ${space.name}. Everything inside is unfiled again.`)
                // pinned: analytics event name. Renaming it breaks dashboards.
                posthog.capture('analytics space deleted')
                actions.deleteSpaceDone(true)
                actions.loadShortcuts()
                actions.loadSpaces()
                router.actions.push(urls.analyticsSpaces())
            } catch (error) {
                lemonToast.error(error instanceof Error ? error.message : 'Could not delete this space.')
                actions.deleteSpaceDone(false)
            }
        },
        toggleStarDone: () => {
            // pinned: analytics event name and property. Renaming them breaks dashboards.
            posthog.capture('analytics space starred', { starred_count: values.starredSpaces.length })
        },
    })),
    // The sidebar mounts this logic for the stars alone; counting every space is for the Spaces page.
    urlToAction(({ actions, values }) => ({
        [urls.analyticsSpaces()]: () => {
            if (values.featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]) {
                actions.loadSpaces()
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        if (values.featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]) {
            cache.flagSeen = true
            actions.loadShortcuts()
        }
    }),
])
