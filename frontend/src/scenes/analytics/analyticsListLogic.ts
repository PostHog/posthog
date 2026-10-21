import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { AnalyticsListUrlParams, urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { isPathUnder, joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { todayAnalyticsLogic } from '~/layout/today/todayAnalyticsLogic'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import type { UserBasicType, UserType } from '~/types'

import {
    ANALYTICS_FEED_PAGE_SIZE,
    AnalyticsFeed,
    AnalyticsFeedQuery,
    AnalyticsSourceState,
    analyticsFeedTypes,
    analyticsSourceKey,
} from './analyticsFeed'
import { analyticsFeedLogic, selectAnalyticsFeed } from './analyticsFeedLogic'
import { analyticsShareLogic } from './analyticsShareLogic'
import {
    ANALYTICS_FILE_SYSTEM_TYPES,
    AnalyticsItem,
    AnalyticsTypeFilter,
    fileSystemBaseType,
    fileSystemEntryName,
    fileSystemEntryToAnalytics,
    isAnalyticsType,
} from './analyticsUtils'

export const ANALYTICS_PREFETCH_COUNT = ANALYTICS_FEED_PAGE_SIZE
// A folder lists its direct children in one request. Deeper folders are opened by drilling in.
const FOLDER_PAGE_SIZE = ANALYTICS_FEED_PAGE_SIZE
const SORT_TEAM_ID = getCurrentTeamIdOrNone()
const SORT_USER_ID = getCurrentUserIdOrNone()
const SORT_PERSIST_OPTIONS =
    SORT_TEAM_ID && SORT_USER_ID ? { persist: true, prefix: `${SORT_TEAM_ID}__${SORT_USER_ID}__` } : { persist: false }

export interface AnalyticsListFilters {
    type: AnalyticsTypeFilter
    orderBy?: AnalyticsFeedQuery['orderBy']
    search: string
    /** User uuids; empty means anyone. */
    createdBy: string[]
    /** A file system folder path to browse, '' for the project root, or null for the whole project. */
    folder: string | null
    tags: string[]
}

export const DEFAULT_ANALYTICS_LIST_FILTERS: AnalyticsListFilters = {
    type: 'all',
    search: '',
    createdBy: [],
    folder: null,
    tags: [],
}

export type AnalyticsListMode = 'feed' | 'folder'
/** `all` lists what the project shares; `mine` lists everything the person created, shared or not. */
export type AnalyticsListScope = 'all' | 'mine'
type AnalyticsSortChoices = Partial<Record<AnalyticsListScope, NonNullable<AnalyticsFeedQuery['orderBy']>>>

export interface FolderContents {
    /** The folder these rows belong to, so a failed or slow load never shows another folder's rows. */
    folder: string
    hasMore: boolean
    entries: FileSystemEntry[]
    users: UserBasicType[]
}

export interface FolderRow {
    path: string
    name: string
    entry?: FileSystemEntry
    createdAt?: string | null
    createdBy?: AnalyticsItem['createdBy']
}

export type AnalyticsListState = 'loading' | 'error' | 'empty' | 'no-matches' | 'ready'

function stringList(value: unknown): string[] {
    if (typeof value === 'string') {
        return value ? [value] : []
    }
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

/** The router reads a value that looks like a number or a boolean as one, so text goes back to a string. */
function urlParamToString(value: unknown): string {
    return `${value ?? ''}`
}

export function analyticsListFiltersFromUrl(params: Record<string, any>): AnalyticsListFilters {
    const type = typeof params.type === 'string' && isAnalyticsType(params.type) ? params.type : 'all'
    const tags = Array.isArray(params.tags)
        ? params.tags.filter((tag: unknown): tag is string => typeof tag === 'string')
        : []
    return {
        type,
        orderBy: ['-created_at', '-last_viewed_at', 'last_viewed_at'].includes(params.orderBy)
            ? params.orderBy
            : undefined,
        search: urlParamToString(params.search),
        createdBy: stringList(params.createdBy),
        folder: params.folder === undefined || params.folder === null ? null : urlParamToString(params.folder),
        tags,
    }
}

export function analyticsListUrlParams(filters: AnalyticsListFilters): AnalyticsListUrlParams {
    return {
        orderBy: filters.orderBy,
        type: filters.type === 'all' ? undefined : filters.type,
        search: filters.search.trim() || undefined,
        createdBy: filters.createdBy.length ? filters.createdBy : undefined,
        folder: filters.folder ?? undefined,
        tags: filters.tags.length ? filters.tags : undefined,
    }
}

export function analyticsListFiltersActive(filters: AnalyticsListFilters): boolean {
    return filters.type !== 'all' || !!filters.search.trim() || filters.createdBy.length > 0 || filters.tags.length > 0
}

/** Narrows rows the server did not filter: folder contents come back whole. */
export function filterAnalytics(items: AnalyticsItem[], filters: AnalyticsListFilters): AnalyticsItem[] {
    const needle = filters.search.trim().toLowerCase()
    const createdBy = filters.createdBy
    return items.filter(
        (item) =>
            filters.tags.every((tag) => item.tags.includes(tag)) &&
            (filters.type === 'all' || item.type === filters.type) &&
            (!needle || item.name.toLowerCase().includes(needle)) &&
            (!createdBy.length || (!!item.createdBy && createdBy.includes(item.createdBy.uuid)))
    )
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface analyticsListLogicValues {
    sources: Record<string, AnalyticsSourceState> // analyticsFeedLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentTeamId: number | null // teamLogic
    user: UserType | null // userLogic
    creators: string[]
    currentFeed: AnalyticsFeed
    currentUserUuid: string | null
    failedTypes: AnalyticsFeed['failedTypes']
    feed: AnalyticsFeed
    feedQuery: AnalyticsFeedQuery
    feedSearch: string
    feedStale: boolean
    filters: AnalyticsListFilters
    filtersActive: boolean
    folderBreadcrumbs: FolderRow[]
    folderContents: FolderContents | null
    folderContentsLoading: boolean
    folderFailed: boolean
    hasMore: boolean
    items: AnalyticsItem[]
    listState: AnalyticsListState
    loadedCount: number
    loading: boolean
    mode: AnalyticsListMode
    scope: AnalyticsListScope
    searchInput: string
    shownQuery: AnalyticsFeedQuery | null
    sortChoicesByScope: AnalyticsSortChoices
    subfolders: FolderRow[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface analyticsListLogicActions {
    ensureFeed: (
        query: AnalyticsFeedQuery,
        count: number
    ) => {
        count: number
        query: AnalyticsFeedQuery
    } // analyticsFeedLogic
    refreshFeed: (query: AnalyticsFeedQuery) => {
        query: AnalyticsFeedQuery
    } // analyticsFeedLogic
    sourceRefreshed: (
        key: string,
        generation: number,
        page: null | import('./analyticsFeed').AnalyticsSourcePage
    ) => {
        generation: number
        key: string
        page: null | import('./analyticsFeed').AnalyticsSourcePage
    } // analyticsFeedLogic
    shareToSpaceDone: () => {
        value: true
    } // analyticsShareLogic
    deleteSavedItem: (savedItem: FileSystemEntry) => {
        savedItem: FileSystemEntry
    } // projectTreeDataLogic
    movesSettled: (moved: import('~/layout/panel-layout/ProjectTree/projectTreeDataLogic').MovedItem[]) => {
        moved: import('~/layout/panel-layout/ProjectTree/projectTreeDataLogic').MovedItem[]
    } // projectTreeDataLogic
    folderCreated: () => {
        value: true
    } // todayAnalyticsLogic
    clearFilters: () => {
        value: true
    }
    loadFolderContents: (_: void) => void
    loadFolderContentsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadFolderContentsSuccess: (
        folderContents: {
            entries: FileSystemEntry[]
            folder: string
            hasMore: boolean
            users: UserBasicType[]
        } | null,
        payload?: void
    ) => {
        folderContents: {
            entries: FileSystemEntry[]
            folder: string
            hasMore: boolean
            users: UserBasicType[]
        } | null
        payload?: void
    }
    loadList: () => {
        value: true
    }
    loadMore: () => {
        value: true
    }
    loadMoreFolderContents: (_: void) => void
    loadMoreFolderContentsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMoreFolderContentsSuccess: (
        folderContents: FolderContents | null,
        payload?: void
    ) => {
        folderContents: FolderContents | null
        payload?: void
    }
    rememberOrderBy: (
        scope: AnalyticsListScope,
        orderBy: NonNullable<AnalyticsFeedQuery['orderBy']>
    ) => {
        orderBy: NonNullable<'-created_at' | '-last_viewed_at' | 'last_viewed_at' | undefined>
        scope: AnalyticsListScope
    }
    setFeedSearch: (search: string) => {
        search: string
    }
    setFilters: (filters: Partial<AnalyticsListFilters>) => {
        filters: Partial<AnalyticsListFilters>
    }
    setFiltersFromUrl: (filters: AnalyticsListFilters) => {
        filters: AnalyticsListFilters
    }
    setScope: (scope: AnalyticsListScope) => {
        scope: AnalyticsListScope
    }
    setSearchInput: (search: string) => {
        search: string
    }
    setShownQuery: (query: AnalyticsFeedQuery) => {
        query: AnalyticsFeedQuery
    }
    storeFilters: (filters: AnalyticsListFilters) => {
        filters: AnalyticsListFilters
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface analyticsListLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        mode: (filters: AnalyticsListFilters) => AnalyticsListMode
        filtersActive: (filters: AnalyticsListFilters) => boolean
        currentUserUuid: (user: UserType | null) => string | null
        creators: (filters: AnalyticsListFilters, currentUserUuid: string | null, scope: AnalyticsListScope) => string[]
        feedQuery: (
            filters: AnalyticsListFilters,
            feedSearch: string,
            creators: string[],
            currentUserUuid: string | null,
            scope: AnalyticsListScope,
            sortChoicesByScope: Partial<
                Record<
                    AnalyticsListScope,
                    NonNullable<'-created_at' | '-last_viewed_at' | 'last_viewed_at' | undefined>
                >
            >
        ) => AnalyticsFeedQuery
        currentFeed: (
            sources: Record<string, AnalyticsSourceState>,
            currentTeamId: number | null,
            feedQuery: AnalyticsFeedQuery
        ) => AnalyticsFeed
        feed: (
            currentFeed: AnalyticsFeed,
            sources: Record<string, AnalyticsSourceState>,
            currentTeamId: number | null,
            shownQuery: AnalyticsFeedQuery | null
        ) => AnalyticsFeed
        feedStale: (currentFeed: AnalyticsFeed, feed: AnalyticsFeed) => boolean
        items: (
            mode: AnalyticsListMode,
            feed: AnalyticsFeed,
            folderContents: FolderContents | null,
            filters: AnalyticsListFilters
        ) => AnalyticsItem[]
        subfolders: (
            mode: AnalyticsListMode,
            folderContents: FolderContents | null,
            filters: AnalyticsListFilters
        ) => FolderRow[]
        folderBreadcrumbs: (filters: AnalyticsListFilters) => FolderRow[]
        loading: (mode: AnalyticsListMode, feed: AnalyticsFeed, folderContentsLoading: boolean) => boolean
        loadedCount: (
            mode: AnalyticsListMode,
            sources: Record<string, AnalyticsSourceState>,
            feedQuery: AnalyticsFeedQuery,
            currentTeamId: number | null,
            folderContents: FolderContents | null
        ) => number
        hasMore: (
            mode: AnalyticsListMode,
            feed: AnalyticsFeed,
            folderContents: FolderContents | null,
            filters: AnalyticsListFilters
        ) => boolean
        failedTypes: (mode: AnalyticsListMode, feed: AnalyticsFeed) => AnalyticsFeed['failedTypes']
        listState: (
            mode: AnalyticsListMode,
            feed: AnalyticsFeed,
            folderContents: FolderContents | null,
            folderFailed: boolean,
            items: AnalyticsItem[],
            subfolders: FolderRow[],
            filtersActive: boolean
        ) => AnalyticsListState
    }
}

export type analyticsListLogicType = MakeLogicType<
    analyticsListLogicValues,
    analyticsListLogicActions,
    Record<string, any>,
    analyticsListLogicMeta
>

export const analyticsListLogic = kea<analyticsListLogicType>([
    path(['scenes', 'analytics', 'analyticsListLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user'],
            analyticsFeedLogic,
            ['sources'],
        ],
        actions: [
            analyticsFeedLogic,
            ['ensureFeed', 'refreshFeed', 'sourceRefreshed'],
            analyticsShareLogic,
            ['shareToSpaceDone'],
            todayAnalyticsLogic,
            ['folderCreated'],
            projectTreeDataLogic,
            ['movesSettled', 'deleteSavedItem'],
        ],
    })),
    actions({
        setScope: (scope: AnalyticsListScope) => ({ scope }),
        setFilters: (filters: Partial<AnalyticsListFilters>) => ({ filters }),
        rememberOrderBy: (scope: AnalyticsListScope, orderBy: NonNullable<AnalyticsFeedQuery['orderBy']>) => ({
            scope,
            orderBy,
        }),
        setFiltersFromUrl: (filters: AnalyticsListFilters) => ({ filters }),
        /** Remembers URL filters without reading anything, for a visit the flag does not render yet. */
        storeFilters: (filters: AnalyticsListFilters) => ({ filters }),
        clearFilters: true,
        setSearchInput: (search: string) => ({ search }),
        setFeedSearch: (search: string) => ({ search }),
        setShownQuery: (query: AnalyticsFeedQuery) => ({ query }),
        loadList: true,
        loadMore: true,
    }),
    loaders(({ values }) => ({
        folderContents: [
            null as FolderContents | null,
            {
                loadFolderContents: async (_: void, breakpoint) => {
                    const folder = values.filters.folder
                    if (folder === null) {
                        return null
                    }
                    const response = await api.fileSystem.list({
                        parent: folder,
                        depth: splitPath(folder).length + 1,
                        search: values.filters.search.trim() || undefined,
                        limit: FOLDER_PAGE_SIZE,
                    })
                    breakpoint()
                    return {
                        folder,
                        entries: response.results,
                        users: response.users,
                        hasMore: !!response.next,
                    }
                },
                loadMoreFolderContents: async (_: void, breakpoint) => {
                    const current = values.folderContents
                    if (!current || !current.hasMore || current.folder !== values.filters.folder) {
                        return current
                    }
                    const response = await api.fileSystem.list({
                        parent: current.folder,
                        depth: splitPath(current.folder).length + 1,
                        search: values.filters.search.trim() || undefined,
                        limit: FOLDER_PAGE_SIZE,
                        offset: current.entries.length,
                    })
                    breakpoint()
                    return {
                        ...current,
                        entries: [...current.entries, ...response.results],
                        users: [...current.users, ...response.users],
                        hasMore: !!response.next,
                    }
                },
            },
        ],
    })),
    reducers({
        sortChoicesByScope: [
            {} as AnalyticsSortChoices,
            SORT_PERSIST_OPTIONS,
            {
                rememberOrderBy: (state, { scope, orderBy }) => ({ ...state, [scope]: orderBy }),
            },
        ],
        scope: ['all' as AnalyticsListScope, { setScope: (_, { scope }) => scope }],
        filters: [
            DEFAULT_ANALYTICS_LIST_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                setFiltersFromUrl: (_, { filters }) => filters,
                storeFilters: (_, { filters }) => filters,
                // The folder is where the person is, not a narrowing, so clearing keeps it.
                clearFilters: (state) => ({ ...DEFAULT_ANALYTICS_LIST_FILTERS, folder: state.folder }),
            },
        ],
        // What the person has typed. The filters take it after a pause, so each keystroke is not a request.
        searchInput: [
            '',
            {
                setSearchInput: (_, { search }) => search,
                setFiltersFromUrl: (_, { filters }) => filters.search,
                storeFilters: (_, { filters }) => filters.search,
                clearFilters: () => '',
            },
        ],
        feedSearch: ['', { setFeedSearch: (_, { search }) => search }],
        shownQuery: [null as AnalyticsFeedQuery | null, { setShownQuery: (_, { query }) => query }],
        folderFailed: [
            false,
            {
                loadFolderContents: () => false,
                loadFolderContentsFailure: () => true,
            },
        ],
    }),
    selectors({
        mode: [
            (s) => [s.filters],
            (filters: AnalyticsListFilters): AnalyticsListMode => (filters.folder !== null ? 'folder' : 'feed'),
        ],
        filtersActive: [
            (s) => [s.filters],
            (filters: AnalyticsListFilters): boolean => analyticsListFiltersActive(filters),
        ],
        // My work narrows to the person; View all narrows to whoever they picked.
        // The user record is replaced on every reload; its uuid is not, so the feed query only changes when the person does.
        currentUserUuid: [(s) => [s.user], (user: UserType | null): string | null => user?.uuid ?? null],
        creators: [
            (s) => [s.filters, s.currentUserUuid, s.scope],
            (filters: AnalyticsListFilters, currentUserUuid: string | null, scope: AnalyticsListScope): string[] =>
                scope === 'mine' ? (currentUserUuid ? [currentUserUuid] : []) : filters.createdBy,
        ],
        feedQuery: [
            (s) => [s.filters, s.feedSearch, s.creators, s.currentUserUuid, s.scope, s.sortChoicesByScope],
            (
                filters: AnalyticsListFilters,
                feedSearch: string,
                creators: string[],
                currentUserUuid: string | null,
                scope: AnalyticsListScope,
                sortChoicesByScope: AnalyticsSortChoices
            ): AnalyticsFeedQuery => ({
                type: filters.type,
                orderBy: filters.orderBy ?? sortChoicesByScope[scope] ?? '-last_viewed_at',
                search: feedSearch.trim(),
                createdBy: creators,
                createdByMe: !!currentUserUuid && creators.length === 1 && creators[0] === currentUserUuid,
                tags: filters.tags,
            }),
        ],
        currentFeed: [
            (s) => [s.sources, s.currentTeamId, s.feedQuery],
            (
                sources: Record<string, AnalyticsSourceState>,
                currentTeamId: number | null,
                feedQuery: AnalyticsFeedQuery
            ): AnalyticsFeed => selectAnalyticsFeed(sources, currentTeamId, feedQuery),
        ],
        // While a new query loads, the last loaded list stays on screen, dimmed, so the page does not blink.
        feed: [
            (s) => [s.currentFeed, s.sources, s.currentTeamId, s.shownQuery],
            (
                currentFeed: AnalyticsFeed,
                sources: Record<string, AnalyticsSourceState>,
                currentTeamId: number | null,
                shownQuery: AnalyticsFeedQuery | null
            ): AnalyticsFeed => {
                if (currentFeed.initialized || !shownQuery) {
                    return currentFeed
                }
                const shownFeed = selectAnalyticsFeed(sources, currentTeamId, shownQuery)
                return shownFeed.initialized ? { ...shownFeed, loading: true, hasMore: false } : currentFeed
            },
        ],
        feedStale: [
            (s) => [s.currentFeed, s.feed],
            (currentFeed: AnalyticsFeed, feed: AnalyticsFeed): boolean => !currentFeed.initialized && feed.initialized,
        ],
        items: [
            (s) => [s.mode, s.feed, s.folderContents, s.filters],
            (
                mode: AnalyticsListMode,
                feed: AnalyticsFeed,
                folderContents: FolderContents | null,
                filters: AnalyticsListFilters
            ): AnalyticsItem[] => {
                if (mode === 'feed') {
                    return feed.items
                }
                const entries = folderContents?.folder === filters.folder ? folderContents.entries : []
                const items = entries.flatMap((entry) => {
                    const item = ANALYTICS_FILE_SYSTEM_TYPES.has(fileSystemBaseType(entry.type))
                        ? fileSystemEntryToAnalytics(entry, folderContents?.users ?? [])
                        : null
                    return item ? [item] : []
                })
                return filterAnalytics(items, filters)
            },
        ],
        subfolders: [
            (s) => [s.mode, s.folderContents, s.filters],
            (
                mode: AnalyticsListMode,
                folderContents: FolderContents | null,
                filters: AnalyticsListFilters
            ): FolderRow[] => {
                if (mode !== 'folder' || !folderContents || folderContents.folder !== filters.folder) {
                    return []
                }
                // Folders carry no tags, so a tag filter leaves them out.
                if (filters.tags.length) {
                    return []
                }
                const needle = filters.search.trim().toLowerCase()
                return folderContents.entries
                    .filter((entry) => entry.type === 'folder')
                    .map((entry) => {
                        const creator = folderContents.users.find((user) => user.id === entry.meta?.created_by)
                        return {
                            path: entry.path,
                            name: fileSystemEntryName(entry),
                            entry,
                            createdAt: entry.created_at ?? null,
                            createdBy: creator
                                ? {
                                      uuid: creator.uuid,
                                      first_name: creator.first_name,
                                      last_name: creator.last_name,
                                      email: creator.email,
                                  }
                                : null,
                        }
                    })
                    .filter((folder) => !needle || folder.name.toLowerCase().includes(needle))
                    .sort((first, second) => first.name.localeCompare(second.name))
            },
        ],
        folderBreadcrumbs: [
            (s) => [s.filters],
            (filters: AnalyticsListFilters): FolderRow[] => {
                if (filters.folder === null) {
                    return []
                }
                const segments = splitPath(filters.folder)
                return segments.map((segment, index) => ({
                    name: segment,
                    path: joinPath(segments.slice(0, index + 1)),
                }))
            },
        ],
        loading: [
            (s) => [s.mode, s.feed, s.folderContentsLoading],
            (mode: AnalyticsListMode, feed: AnalyticsFeed, folderContentsLoading: boolean): boolean =>
                mode === 'feed' ? feed.loading : folderContentsLoading,
        ],
        // Rows fetched so far, before the client-side filters, so the scroll sentinel re-checks after every page
        // even when a page added nothing visible.
        loadedCount: [
            (s) => [s.mode, s.sources, s.feedQuery, s.currentTeamId, s.folderContents],
            (
                mode: AnalyticsListMode,
                sources: Record<string, AnalyticsSourceState>,
                feedQuery: AnalyticsFeedQuery,
                currentTeamId: number | null,
                folderContents: FolderContents | null
            ): number =>
                mode === 'folder'
                    ? (folderContents?.entries.length ?? 0)
                    : analyticsFeedTypes(feedQuery).reduce(
                          (sum, type) =>
                              sum + (sources[analyticsSourceKey(String(currentTeamId), feedQuery, type)]?.offset ?? 0),
                          0
                      ),
        ],
        hasMore: [
            (s) => [s.mode, s.feed, s.folderContents, s.filters],
            (
                mode: AnalyticsListMode,
                feed: AnalyticsFeed,
                folderContents: FolderContents | null,
                filters: AnalyticsListFilters
            ): boolean =>
                mode === 'feed'
                    ? feed.hasMore
                    : !!folderContents && folderContents.folder === filters.folder && folderContents.hasMore,
        ],
        failedTypes: [
            (s) => [s.mode, s.feed],
            (mode: AnalyticsListMode, feed: AnalyticsFeed): AnalyticsFeed['failedTypes'] =>
                mode === 'feed' ? feed.failedTypes : [],
        ],
        listState: [
            (s) => [s.mode, s.feed, s.folderContents, s.folderFailed, s.items, s.subfolders, s.filtersActive],
            (
                mode: AnalyticsListMode,
                feed: AnalyticsFeed,
                folderContents: FolderContents | null,
                folderFailed: boolean,
                items: AnalyticsItem[],
                subfolders: FolderRow[],
                filtersActive: boolean
            ): AnalyticsListState => {
                const resolved = mode === 'feed' ? feed.initialized : folderContents !== null
                const failed = mode === 'feed' ? feed.loadFailed : folderFailed
                if (failed && !items.length) {
                    return 'error'
                }
                if (!resolved) {
                    return 'loading'
                }
                if (items.length || subfolders.length) {
                    return 'ready'
                }
                // Pages can still hold rows a client-side filter left out, so an empty list is not final yet.
                if (mode === 'feed' && feed.hasMore) {
                    return 'loading'
                }
                return filtersActive ? 'no-matches' : 'empty'
            },
        ],
    }),
    listeners(({ actions, values, cache }) => {
        // Once per visit, however many pages the visit reads.
        const reportListLoaded = (viewCount: number, hasMore: boolean): void => {
            if (cache.visitStartedAt === undefined) {
                return
            }
            // pinned: analytics event name and properties. Renaming them breaks dashboards.
            posthog.capture('views list loaded', {
                duration_ms: Math.round(performance.now() - cache.visitStartedAt),
                cached: cache.visitCached,
                view_count: viewCount,
                has_more: hasMore,
                mode: values.mode,
            })
            cache.visitStartedAt = undefined
        }
        const syncShownQuery = (): void => {
            if (values.currentFeed.initialized) {
                if (values.shownQuery !== values.feedQuery) {
                    actions.setShownQuery(values.feedQuery)
                }
                reportListLoaded(values.currentFeed.items.length, values.currentFeed.hasMore)
            }
        }
        const loadCurrentMode = (): void => {
            if (values.mode === 'feed') {
                actions.ensureFeed(values.feedQuery, ANALYTICS_PREFETCH_COUNT)
                syncShownQuery()
            } else {
                actions.loadFolderContents()
            }
        }
        return {
            [featureFlagLogic.actionTypes.setFeatureFlags]: () => {
                // Flags can arrive after urlToAction ran, so a visit that skipped the load must load now.
                if (
                    values.featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] &&
                    cache.visitStartedAt === undefined &&
                    !values.loading &&
                    [urls.analyticsList(), urls.analyticsMine()].includes(
                        removeProjectIdIfPresent(router.values.location.pathname)
                    )
                ) {
                    actions.loadList()
                }
            },
            loadList: () => {
                cache.visitStartedAt = performance.now()
                cache.visitCached = values.mode === 'feed' ? values.currentFeed.initialized : !!values.folderContents
                if (values.mode === 'feed') {
                    actions.refreshFeed(values.feedQuery)
                    syncShownQuery()
                } else {
                    actions.loadFolderContents()
                }
            },
            loadMore: () => {
                if (!values.hasMore) {
                    return
                }
                if (values.mode === 'folder') {
                    actions.loadMoreFolderContents()
                } else {
                    actions.ensureFeed(values.feedQuery, values.feed.items.length + ANALYTICS_PREFETCH_COUNT)
                }
            },
            setSearchInput: async ({ search }, breakpoint) => {
                if (search.trim() !== values.filters.search.trim()) {
                    await breakpoint(search.trim() ? 200 : 0)
                }
                actions.setFilters({ search })
            },
            setFilters: ({ filters }) => {
                if (filters.orderBy) {
                    actions.rememberOrderBy(values.scope, filters.orderBy)
                }
                if (filters.search !== undefined) {
                    actions.setFeedSearch(filters.search)
                }
                const changed = Object.keys(filters).filter((key) => key !== 'search')
                if (changed.length) {
                    // pinned: analytics event name and `type` property. Renaming them breaks dashboards.
                    posthog.capture('views list filtered', {
                        type: values.filters.type,
                        changed,
                        created_by: !values.filters.createdBy.length
                            ? 'anyone'
                            : values.user?.uuid && values.filters.createdBy.includes(values.user.uuid)
                              ? 'me'
                              : 'other',
                        folder: values.filters.folder !== null,
                        tag_count: values.filters.tags.length,
                    })
                }
                loadCurrentMode()
            },
            setFiltersFromUrl: () => {
                actions.setFeedSearch(values.filters.search)
                actions.loadList()
            },
            clearFilters: () => {
                actions.setFeedSearch('')
                loadCurrentMode()
            },
            sourceRefreshed: () => {
                syncShownQuery()
                // Unfiled rows stay hidden, so a page can add nothing visible; keep reading until the list fills.
                if (values.mode === 'feed' && values.hasMore && values.items.length < ANALYTICS_PREFETCH_COUNT) {
                    actions.loadMore()
                }
            },
            loadFolderContentsSuccess: ({ folderContents }) => {
                if (!folderContents) {
                    return
                }
                reportListLoaded(folderContents.entries.length, folderContents.hasMore)
                if (cache.openedFolder !== folderContents.folder) {
                    cache.openedFolder = folderContents.folder
                    // pinned: analytics event name and properties. Renaming them breaks dashboards.
                    posthog.capture('analytics collection opened', {
                        nested: splitPath(folderContents.folder).length > 1,
                        item_count: folderContents.entries.length,
                    })
                }
            },
            // A move or a new folder changes what this list holds, so it reads again.
            shareToSpaceDone: () => actions.loadList(),
            folderCreated: () => actions.loadList(),
            // Drags and folder deletes go through the project tree, which reports here once they land.
            movesSettled: () => actions.loadList(),
            deleteSavedItem: ({ savedItem }) => {
                const folder = values.filters.folder
                if (savedItem.type === 'folder' && folder && isPathUnder(folder, savedItem.path)) {
                    const parent = splitPath(savedItem.path).slice(0, -1)
                    router.actions.push(
                        parent.length ? urls.analyticsList({ folder: joinPath(parent) }) : urls.analyticsSpaces()
                    )
                    return
                }
                actions.loadList()
            },
        }
    }),
    actionToUrl(({ values }) => {
        const toUrl = (): string => {
            return values.scope === 'mine'
                ? urls.analyticsMine(analyticsListUrlParams(values.filters))
                : urls.analyticsList(analyticsListUrlParams(values.filters))
        }
        return {
            setFilters: toUrl,
            clearFilters: toUrl,
        }
    }),
    urlToAction(({ actions, values, cache }) => {
        const listPaths = [urls.analyticsList(), urls.analyticsMine()]
        // The router only writes a URL that differs from the current one, so our own write is the one location
        // change that moves the URL within this scene while the scope and filters stay as they are.
        const isOwnUrlWrite = (previous: { pathname: string; search: string }): boolean =>
            listPaths.includes(removeProjectIdIfPresent(previous.pathname)) &&
            previous.search !== router.values.location.search
        const open = (
            scope: AnalyticsListScope,
            searchParams: Record<string, any>,
            previous: { pathname: string; search: string }
        ): void => {
            const scopeChanged = values.scope !== scope
            if (scopeChanged) {
                actions.setScope(scope)
            }
            // The filters apply even before the flags arrive, so a cold open lands on the right list once they do.
            const filters = analyticsListFiltersFromUrl(searchParams)
            const filtersChanged = JSON.stringify(filters) !== JSON.stringify(values.filters)
            // The scene renders nothing without the flag, so it must not load anything either.
            if (!values.featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]) {
                if (filtersChanged) {
                    actions.storeFilters(filters)
                }
                return
            }
            if (filtersChanged) {
                // A cold open with filters is a visit too, so it reports `views list loaded` like a plain one.
                cache.visitStartedAt = performance.now()
                cache.visitCached = false
                actions.setFiltersFromUrl(filters)
            } else if (scopeChanged || !isOwnUrlWrite(previous)) {
                // A visit shows the last loaded rows at once and reads again, so a new item shows up on return.
                actions.loadList()
            }
        }
        return {
            [urls.analyticsList()]: (_, searchParams, __, ___, previous) => open('all', searchParams, previous),
            [urls.analyticsMine()]: (_, searchParams, __, ___, previous) => open('mine', searchParams, previous),
        }
    }),
])
