import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
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

/** A pinned space: its shortcut row, so the pin can be removed again. */
export interface PinnedSpace {
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
    pinnedPaths: Set<string>
    pinnedSpaces: PinnedSpace[]
    pinning: string | null
    search: string
    shortcuts: FileSystemEntry[]
    shortcutsLoading: boolean
    spaces: AnalyticsSpace[]
    spacesFailed: boolean
    spacesLoading: boolean
    visibleSpaces: AnalyticsSpace[]
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
    setSearch: (search: string) => {
        search: string
    }
    togglePin: (space: Pick<AnalyticsSpace, 'name' | 'path'>) => {
        space: Pick<AnalyticsSpace, 'name' | 'path'>
    }
    togglePinDone: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface analyticsSpacesLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        pinnedSpaces: (shortcuts: FileSystemEntry[]) => PinnedSpace[]
        pinnedPaths: (pinnedSpaces: PinnedSpace[]) => Set<string>
        visibleSpaces: (spaces: AnalyticsSpace[], pinnedPaths: Set<string>, search: string) => AnalyticsSpace[]
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
        togglePin: (space: Pick<AnalyticsSpace, 'path' | 'name'>) => ({ space }),
        togglePinDone: true,
        setSearch: (search: string) => ({ search }),
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
        // The path being pinned or unpinned, so its button shows progress and ignores a second click.
        pinning: [null as string | null, { togglePin: (_, { space }) => space.path, togglePinDone: () => null }],
        search: ['', { setSearch: (_, { search }) => search }],
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
        pinnedSpaces: [
            (s) => [s.shortcuts],
            (shortcuts: FileSystemEntry[]): PinnedSpace[] =>
                shortcuts.flatMap((shortcut) =>
                    // A shortcut's `path` is its display name; `ref` holds the folder it points at.
                    shortcut.type === 'folder' && shortcut.id && shortcut.ref && isSpacePath(shortcut.ref)
                        ? [
                              {
                                  shortcutId: shortcut.id,
                                  path: shortcut.ref,
                                  name: fileSystemEntryName({ path: shortcut.ref }),
                              },
                          ]
                        : []
                ),
        ],
        pinnedPaths: [
            (s) => [s.pinnedSpaces],
            (pinnedSpaces: PinnedSpace[]): Set<string> => new Set(pinnedSpaces.map((space) => space.path)),
        ],
        // Pinned spaces lead, then the rest alphabetically; a search narrows both by name.
        visibleSpaces: [
            (s) => [s.spaces, s.pinnedPaths, s.search],
            (spaces: AnalyticsSpace[], pinnedPaths: Set<string>, search: string): AnalyticsSpace[] => {
                const needle = search.trim().toLowerCase()
                return spaces
                    .filter((space) => !needle || space.name.toLowerCase().includes(needle))
                    .sort((first, second) => {
                        const pinnedFirst = Number(pinnedPaths.has(second.path)) - Number(pinnedPaths.has(first.path))
                        return pinnedFirst || first.name.localeCompare(second.name)
                    })
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        togglePin: async ({ space }) => {
            try {
                const pinned = values.pinnedSpaces.find((candidate) => candidate.path === space.path)
                if (pinned) {
                    await api.fileSystemShortcuts.delete(pinned.shortcutId)
                    toast.success({ title: `Unpinned ${space.name}` })
                } else {
                    // A folder shortcut keeps its path as ref, so a rename moves the star with the folder.
                    await api.fileSystemShortcuts.create({ path: space.path, type: 'folder', ref: space.path })
                    toast.success({ title: `Pinned ${space.name} to the sidebar` })
                }
                actions.loadShortcuts()
            } catch {
                toast.error({ title: 'Couldn’t update the pin. Try again.' })
            }
            actions.togglePinDone()
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
                    throw new Error('This collection has no folder row.')
                }
                await emptySpace(space.path)
                const left = await api.fileSystem.list({ parent: space.path, notType: 'folder', limit: 1 })
                if ((left.count ?? left.results.length) > 0) {
                    throw new Error('Some items could not be moved, so the collection stays.')
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
                const pin = values.pinnedSpaces.find((candidate) => candidate.path === space.path)
                if (pin) {
                    await api.fileSystemShortcuts.delete(pin.shortcutId)
                }
                toast.success({ title: `Deleted ${space.name}. Everything inside is unfiled again.` })
                // pinned: analytics event name. Renaming it breaks dashboards.
                posthog.capture('analytics collection deleted')
                actions.deleteSpaceDone(true)
                actions.loadShortcuts()
                actions.loadSpaces()
                router.actions.push(urls.analyticsSpaces())
            } catch (error) {
                toast.error({
                    title: error instanceof Error ? error.message : 'Couldn’t delete this collection. Try again.',
                })
                actions.deleteSpaceDone(false)
            }
        },
        togglePinDone: () => {
            // pinned: analytics event name and property. Renaming them breaks dashboards.
            posthog.capture('analytics collection pinned', { pinned_count: values.pinnedSpaces.length })
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
