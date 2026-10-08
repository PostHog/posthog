import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import type { LocationChangedPayload } from 'kea-router/lib/types'
import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { writeToClipboard } from 'lib/utils/writeToClipboard'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ConversationDetail, UserType } from '~/types'

import {
    taskActivityList,
    taskActivityMarkReadCreate,
    taskChannelsList,
    taskChannelsStarCreate,
    tasksList,
    tasksSummariesCreate,
} from 'products/tasks/frontend/generated/api'
import {
    ChannelDTOApi,
    PrStateEnumApi,
    TaskActivityDTOApi,
    TaskActivityReadMarkerApi,
    TaskListItemApi,
} from 'products/tasks/frontend/generated/api.schemas'
import { pullRequestStates, sessionIdsWithPullRequests } from 'products/tasks/frontend/spaces/taskPullRequests'

import { matchesPaneQuery } from './todayPaneSearch'
import {
    DEFAULT_RECENT_FILTERS,
    TodayRecentFilters,
    filterRecentItems,
    hasActiveRecentFilters,
    recentSourceOptions,
    withRecentFilterDefaults,
} from './todayRecentFilters'
import {
    DEFAULT_RECENT_GROUPING,
    DEFAULT_RECENT_SORT,
    TodayRecentGrouping,
    TodayRecentSection,
    TodayRecentSort,
    groupRecentItems,
    sortRecentItems,
} from './todayRecentOrder'
import {
    TodayWorkItem,
    buildRecentItems,
    sessionItem,
    sessionReadRequest,
    setActivityUnread,
    unreadSessionIds,
} from './todayWorkItems'

const PINNED_SESSION_LIMIT = 20
const RECENT_SESSION_LIMIT = 30
const RECENT_ITEM_LIMIT = 30
// One page of the requester's newest activity. Unread state older than this does not show on the rail.
const UNREAD_ACTIVITY_LIMIT = 200
// The sidebar and a space scene both refresh on mount, so collapse their requests into one.
const UNREAD_ACTIVITY_DEBOUNCE_MS = 100
// Other clients start sessions this tab never hears about, so Recent reloads on a timer and on each return to
// the tab, and the cooldown holds a flick between tabs to one request.
const RECENT_REFRESH_INTERVAL_MS = 60_000
const RECENT_REFRESH_COOLDOWN_MS = 15_000

export type TodayWorkSectionId = 'pinned' | 'recent'

export type TodayTouchMenu = 'session' | 'space' | 'bulk' | 'filter' | 'chat'

/** The space a path is in, like PostHog Desktop's scoped space. `/spaces/new` is in no space. */
export function spaceIdForPath(pathname: string): string | null {
    const match = removeProjectIdIfPresent(pathname).match(/^\/spaces\/([^/]+)/)
    return match && match[1] !== 'new' ? match[1] : null
}

export function recentRefreshIsDue(loadedAt: number | undefined, now: number = Date.now()): boolean {
    return loadedAt === undefined || now - loadedAt >= RECENT_REFRESH_COOLDOWN_MS
}

/** The personal space first, then the team's general space, then starred spaces, then the rest by name. */
export function sortSpaces(spaces: ChannelDTOApi[]): ChannelDTOApi[] {
    const rank = (space: ChannelDTOApi): number =>
        space.system_role === 'personal' ? 0 : space.system_role === 'general' ? 1 : space.starred ? 2 : 3
    return [...spaces].sort((first, second) => rank(first) - rank(second) || first.name.localeCompare(second.name))
}

export function spaceLabel(space: Pick<ChannelDTOApi, 'name' | 'system_role'>): string {
    return space.system_role === 'personal' ? 'personal' : space.name
}

/** Only some people can see it: the personal space, or a private shared space. */
export function isLockedSpace(space: Pick<ChannelDTOApi, 'channel_type' | 'system_role'>): boolean {
    return space.system_role === 'personal' || space.channel_type === 'personal' || space.channel_type === 'private'
}

export function starredSpaces(spaces: ChannelDTOApi[]): ChannelDTOApi[] {
    return [
        ...spaces.filter((space) => space.system_role === 'personal'),
        ...spaces
            .filter((space) => space.system_role !== 'personal' && space.starred)
            .sort((first, second) => first.name.localeCompare(second.name)),
    ]
}

/** The spaces a session can be filed to: its current space first, then starred spaces, then the rest by name. */
export function fileToSpaces(spaces: ChannelDTOApi[], currentSpaceId: string | null, search = ''): ChannelDTOApi[] {
    const query = search.trim().toLowerCase()
    const starred = starredSpaces(spaces)
    const ordered = [
        ...spaces.filter((space) => space.id === currentSpaceId),
        ...starred.filter((space) => space.id !== currentSpaceId),
        ...spaces
            .filter((space) => space.id !== currentSpaceId && !starred.includes(space))
            .sort((first, second) => first.name.localeCompare(second.name)),
    ]
    return query ? ordered.filter((space) => spaceLabel(space).toLowerCase().includes(query)) : ordered
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todaySpacesLogicValues {
    conversationHistory: ConversationDetail[] // maxGlobalLogic
    conversationHistoryLoading: boolean // maxGlobalLogic
    currentTeamId: number | null // teamLogic
    user: UserType | null // userLogic
    allRecentItems: TodayWorkItem[]
    collapsedSections: TodayWorkSectionId[]
    lastSpaceId: string | null
    pendingSpaceIds: string[]
    phoneSection: TodayWorkSectionId
    pinnedItems: TodayWorkItem[]
    pinnedTasks: TaskListItemApi[]
    pinnedTasksLoading: boolean
    pullRequestStates: Record<string, PrStateEnumApi>
    recentFilters: TodayRecentFilters
    recentFiltersActive: boolean
    recentGrouping: TodayRecentGrouping
    recentGroups: TodayRecentSection[]
    recentItems: TodayWorkItem[]
    recentLoading: boolean
    recentQuery: string
    recentSort: TodayRecentSort
    recentSourceOptions: string[]
    recentTasks: TaskListItemApi[]
    recentTasksLoading: boolean
    recentTasksUnavailable: boolean
    sectionHeights: Partial<Record<TodayWorkSectionId, number>>
    shownPinnedItems: TodayWorkItem[]
    sortedSpaces: ChannelDTOApi[]
    spaceNames: Record<string, string>
    spaces: ChannelDTOApi[]
    spacesLoading: boolean
    spacesUnavailable: boolean
    storedRecentFilters: Partial<TodayRecentFilters>
    taskActivity: TaskActivityDTOApi[]
    taskActivityLoading: boolean
    unreadSessionIds: Set<string>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todaySpacesLogicActions {
    locationChanged: ({
        method,
        pathname,
        search,
        searchParams,
        hash,
        hashParams,
        initial,
        url,
        routerState,
    }: LocationChangedPayload) => {
        hash: string
        hashParams: Record<string, any>
        initial: boolean
        method: 'POP' | 'PUSH' | 'REPLACE'
        pathname: string
        routerState: Record<string, any>
        search: string
        searchParams: Record<string, any>
        url: string
    } // router
    clearRecentFilters: () => {
        value: true
    }
    clearRecentSearchAndFilters: () => {
        value: true
    }
    copySpaceLink: (spaceId: string) => {
        spaceId: string
    }
    loadPinnedTasks: () => any
    loadPinnedTasksFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPinnedTasksSuccess: (
        pinnedTasks: TaskListItemApi[],
        payload?: any
    ) => {
        pinnedTasks: TaskListItemApi[]
        payload?: any
    }
    loadPullRequestStates: (sessionIds: string[]) => {
        sessionIds: string[]
    }
    loadRecentTasks: (_: void) => void
    loadRecentTasksFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRecentTasksSuccess: (
        recentTasks: TaskListItemApi[],
        payload?: void
    ) => {
        recentTasks: TaskListItemApi[]
        payload?: void
    }
    loadSpaces: () => any
    loadSpacesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSpacesSuccess: (
        spaces: ChannelDTOApi[],
        payload?: any
    ) => {
        spaces: ChannelDTOApi[]
        payload?: any
    }
    loadTaskActivity: (_: void) => void
    loadTaskActivityFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTaskActivitySuccess: (
        taskActivity: TaskActivityDTOApi[],
        payload?: void
    ) => {
        taskActivity: TaskActivityDTOApi[]
        payload?: void
    }
    markSessionRead: (
        marker: TaskActivityReadMarkerApi,
        activityIds: string[]
    ) => {
        activityIds: string[]
        marker: TaskActivityReadMarkerApi
    }
    markSessionReadFailed: (activityIds: string[]) => {
        activityIds: string[]
    }
    resetSectionPair: (
        upper: TodayWorkSectionId,
        lower: TodayWorkSectionId
    ) => {
        lower: TodayWorkSectionId
        upper: TodayWorkSectionId
    }
    setPhoneSection: (section: TodayWorkSectionId) => {
        section: TodayWorkSectionId
    }
    setPullRequestStates: (states: Record<string, PrStateEnumApi>) => {
        states: Record<string, PrStateEnumApi>
    }
    setRecentFilters: (filters: TodayRecentFilters) => {
        filters: TodayRecentFilters
    }
    setRecentGrouping: (grouping: TodayRecentGrouping) => {
        grouping: TodayRecentGrouping
    }
    setRecentQuery: (query: string) => {
        query: string
    }
    setRecentSort: (sort: TodayRecentSort) => {
        sort: TodayRecentSort
    }
    setSectionHeights: (heights: Partial<Record<TodayWorkSectionId, number>>) => {
        heights: Partial<Record<TodayWorkSectionId, number>>
    }
    spaceVisited: (spaceId: string) => {
        spaceId: string
    }
    starFailed: (spaceId: string) => {
        spaceId: string
    }
    toggleSection: (sectionId: TodayWorkSectionId) => {
        sectionId: TodayWorkSectionId
    }
    toggleStar: (
        spaceId: string,
        starred: boolean
    ) => {
        spaceId: string
        starred: boolean
    }
    touchMenuOpened: (menu: TodayTouchMenu) => {
        menu: TodayTouchMenu
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todaySpacesLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        sortedSpaces: (spaces: ChannelDTOApi[]) => ChannelDTOApi[]
        pinnedItems: (pinnedTasks: TaskListItemApi[]) => TodayWorkItem[]
        allRecentItems: (
            recentTasks: TaskListItemApi[],
            conversationHistory: ConversationDetail[],
            pinnedTasks: TaskListItemApi[]
        ) => TodayWorkItem[]
        recentFilters: (storedRecentFilters: Partial<TodayRecentFilters>) => TodayRecentFilters
        recentSourceOptions: (allRecentItems: TodayWorkItem[], recentFilters: TodayRecentFilters) => string[]
        shownPinnedItems: (pinnedItems: TodayWorkItem[], recentQuery: string) => TodayWorkItem[]
        recentFiltersActive: (recentFilters: TodayRecentFilters) => boolean
        unreadSessionIds: (taskActivity: TaskActivityDTOApi[]) => Set<string>
        recentItems: (
            allRecentItems: TodayWorkItem[],
            recentQuery: string,
            recentFilters: TodayRecentFilters,
            recentSort: TodayRecentSort,
            user: UserType | null,
            unreadSessionIds: Set<string>,
            pinnedItems: TodayWorkItem[]
        ) => TodayWorkItem[]
        spaceNames: (spaces: ChannelDTOApi[]) => Record<string, string>
        recentGroups: (
            recentItems: TodayWorkItem[],
            recentSort: TodayRecentSort,
            recentGrouping: TodayRecentGrouping,
            spaceNames: Record<string, string>
        ) => TodayRecentSection[]
        recentLoading: (recentTasksLoading: boolean, conversationHistoryLoading: boolean) => boolean
    }
}

export type todaySpacesLogicType = MakeLogicType<
    todaySpacesLogicValues,
    todaySpacesLogicActions,
    Record<string, any>,
    todaySpacesLogicMeta
>

export const todaySpacesLogic = kea<todaySpacesLogicType>([
    path(['layout', 'today', 'todaySpacesLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user'],
            maxGlobalLogic,
            ['conversationHistory', 'conversationHistoryLoading'],
        ],
        actions: [router, ['locationChanged']],
    })),
    actions({
        toggleSection: (sectionId: TodayWorkSectionId) => ({ sectionId }),
        setPhoneSection: (section: TodayWorkSectionId) => ({ section }),
        touchMenuOpened: (menu: TodayTouchMenu) => ({ menu }),
        setSectionHeights: (heights: Partial<Record<TodayWorkSectionId, number>>) => ({ heights }),
        resetSectionPair: (upper: TodayWorkSectionId, lower: TodayWorkSectionId) => ({ upper, lower }),
        spaceVisited: (spaceId: string) => ({ spaceId }),
        setRecentQuery: (query: string) => ({ query }),
        setRecentFilters: (filters: TodayRecentFilters) => ({ filters }),
        clearRecentFilters: true,
        clearRecentSearchAndFilters: true,
        setRecentSort: (sort: TodayRecentSort) => ({ sort }),
        setRecentGrouping: (grouping: TodayRecentGrouping) => ({ grouping }),
        toggleStar: (spaceId: string, starred: boolean) => ({ spaceId, starred }),
        starFailed: (spaceId: string) => ({ spaceId }),
        copySpaceLink: (spaceId: string) => ({ spaceId }),
        markSessionRead: (marker: TaskActivityReadMarkerApi, activityIds: string[]) => ({ marker, activityIds }),
        markSessionReadFailed: (activityIds: string[]) => ({ activityIds }),
        loadPullRequestStates: (sessionIds: string[]) => ({ sessionIds }),
        setPullRequestStates: (states: Record<string, PrStateEnumApi>) => ({ states }),
    }),
    loaders(({ values }) => ({
        spaces: [
            [] as ChannelDTOApi[],
            {
                loadSpaces: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await taskChannelsList(String(values.currentTeamId))
                    // Without `limit` the endpoint answers with a bare array rather than a page.
                    return Array.isArray(response) ? (response as ChannelDTOApi[]) : response.results
                },
            },
        ],
        pinnedTasks: [
            [] as TaskListItemApi[],
            {
                loadPinnedTasks: async () => {
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await tasksList(String(values.currentTeamId), {
                        pinned: true,
                        basic: true,
                        limit: PINNED_SESSION_LIMIT,
                    })
                    return response.results
                },
            },
        ],
        recentTasks: [
            [] as TaskListItemApi[],
            {
                loadRecentTasks: async (_: void, breakpoint) => {
                    if (!values.currentTeamId || !values.user) {
                        return []
                    }
                    const response = await tasksList(String(values.currentTeamId), {
                        created_by: values.user.id,
                        ordering: '-last_activity_at',
                        basic: true,
                        limit: RECENT_SESSION_LIMIT,
                    })
                    // A slower earlier reply must not overwrite what a newer refresh already returned.
                    breakpoint()
                    return response.results
                },
            },
        ],
        taskActivity: [
            [] as TaskActivityDTOApi[],
            {
                loadTaskActivity: async (_: void, breakpoint) => {
                    await breakpoint(UNREAD_ACTIVITY_DEBOUNCE_MS)
                    if (!values.currentTeamId) {
                        return []
                    }
                    const response = await taskActivityList(String(values.currentTeamId), {
                        limit: UNREAD_ACTIVITY_LIMIT,
                    })
                    return response.results
                },
            },
        ],
    })),
    reducers({
        pullRequestStates: [
            {} as Record<string, PrStateEnumApi>,
            { setPullRequestStates: (state, { states }) => ({ ...state, ...states }) },
        ],
        collapsedSections: [
            [] as TodayWorkSectionId[],
            { persist: true },
            {
                toggleSection: (state, { sectionId }) =>
                    state.includes(sectionId) ? state.filter((id) => id !== sectionId) : [...state, sectionId],
            },
        ],
        phoneSection: [
            'recent' as TodayWorkSectionId,
            { persist: true },
            { setPhoneSection: (_, { section }) => section },
        ],
        sectionHeights: [
            {} as Partial<Record<TodayWorkSectionId, number>>,
            { persist: true },
            {
                setSectionHeights: (_, { heights }) => heights,
                resetSectionPair: (state, { upper, lower }) => {
                    const { [upper]: _upper, [lower]: _lower, ...rest } = state
                    return rest
                },
            },
        ],
        // A generic New session files here, like PostHog Desktop's scoped space. A stale id falls back to personal.
        lastSpaceId: [null as string | null, { persist: true }, { spaceVisited: (_, { spaceId }) => spaceId }],
        recentQuery: ['', { setRecentQuery: (_, { query }) => query, clearRecentSearchAndFilters: () => '' }],
        storedRecentFilters: [
            DEFAULT_RECENT_FILTERS as Partial<TodayRecentFilters>,
            // pinned: localStorage key. A new key resets every person's saved Recent filters.
            { persist: true, storageKey: 'layout.today.todaySpacesLogic.recentFilters' },
            {
                setRecentFilters: (_, { filters }) => filters,
                clearRecentFilters: () => DEFAULT_RECENT_FILTERS,
                clearRecentSearchAndFilters: () => DEFAULT_RECENT_FILTERS,
            },
        ],
        recentSort: [
            DEFAULT_RECENT_SORT as TodayRecentSort,
            { persist: true },
            { setRecentSort: (_, { sort }) => sort },
        ],
        recentGrouping: [
            DEFAULT_RECENT_GROUPING as TodayRecentGrouping,
            { persist: true },
            { setRecentGrouping: (_, { grouping }) => grouping },
        ],
        pendingSpaceIds: [
            [] as string[],
            {
                toggleStar: (state, { spaceId }) => [...state, spaceId],
                starFailed: (state, { spaceId }) => state.filter((id) => id !== spaceId),
                loadSpacesSuccess: () => [],
                loadSpacesFailure: () => [],
            },
        ],
        spacesUnavailable: [false, { loadSpaces: () => false, loadSpacesFailure: () => true }],
        recentTasksUnavailable: [false, { loadRecentTasks: () => false, loadRecentTasksFailure: () => true }],
        taskActivity: {
            markSessionRead: (state, { activityIds }) => setActivityUnread(state, activityIds, false),
            markSessionReadFailed: (state, { activityIds }) => setActivityUnread(state, activityIds, true),
        },
    }),
    selectors({
        sortedSpaces: [(s) => [s.spaces], (spaces: ChannelDTOApi[]): ChannelDTOApi[] => sortSpaces(spaces)],
        pinnedItems: [
            (s) => [s.pinnedTasks],
            (pinnedTasks: TaskListItemApi[]): TodayWorkItem[] =>
                pinnedTasks.filter((task) => !task.archived).map(sessionItem),
        ],
        allRecentItems: [
            (s) => [s.recentTasks, s.conversationHistory, s.pinnedTasks],
            (
                recentTasks: TaskListItemApi[],
                conversationHistory: ConversationDetail[],
                pinnedTasks: TaskListItemApi[]
            ): TodayWorkItem[] =>
                buildRecentItems(
                    recentTasks,
                    conversationHistory,
                    pinnedTasks.map((task) => task.id),
                    RECENT_ITEM_LIMIT
                ),
        ],
        recentFilters: [
            (s) => [s.storedRecentFilters],
            (storedRecentFilters: Partial<TodayRecentFilters>): TodayRecentFilters =>
                withRecentFilterDefaults(storedRecentFilters),
        ],
        recentSourceOptions: [
            (s) => [s.allRecentItems, s.recentFilters],
            (allRecentItems: TodayWorkItem[], recentFilters: TodayRecentFilters): string[] =>
                recentSourceOptions(allRecentItems, recentFilters.sources),
        ],
        // The pane's search filters every group, so these match on the same terms as the Recent list.
        shownPinnedItems: [
            (s) => [s.pinnedItems, s.recentQuery],
            (pinnedItems: TodayWorkItem[], recentQuery: string): TodayWorkItem[] =>
                pinnedItems.filter((item) => matchesPaneQuery(item.title || '', recentQuery)),
        ],
        recentFiltersActive: [
            (s) => [s.recentFilters],
            (recentFilters: TodayRecentFilters): boolean => hasActiveRecentFilters(recentFilters),
        ],
        unreadSessionIds: [
            (s) => [s.taskActivity],
            (taskActivity: TaskActivityDTOApi[]): Set<string> => unreadSessionIds(taskActivity),
        ],
        recentItems: [
            (s) => [
                s.allRecentItems,
                s.recentQuery,
                s.recentFilters,
                s.recentSort,
                s.user,
                s.unreadSessionIds,
                s.pinnedItems,
            ],
            (
                allRecentItems: TodayWorkItem[],
                recentQuery: string,
                recentFilters: TodayRecentFilters,
                recentSort: TodayRecentSort,
                user: UserType | null,
                unreadSessionIds: Set<string>,
                pinnedItems: TodayWorkItem[]
            ): TodayWorkItem[] =>
                sortRecentItems(
                    filterRecentItems(allRecentItems, recentQuery, recentFilters, {
                        userId: user?.id ?? null,
                        unreadIds: unreadSessionIds,
                        pinnedIds: new Set(pinnedItems.map((item) => item.id)),
                    }),
                    recentSort
                ),
        ],
        spaceNames: [
            (s) => [s.spaces],
            (spaces: ChannelDTOApi[]): Record<string, string> =>
                Object.fromEntries(spaces.map((space) => [space.id, spaceLabel(space)])),
        ],
        recentGroups: [
            (s) => [s.recentItems, s.recentSort, s.recentGrouping, s.spaceNames],
            (
                recentItems: TodayWorkItem[],
                recentSort: TodayRecentSort,
                recentGrouping: TodayRecentGrouping,
                spaceNames: Record<string, string>
            ): TodayRecentSection[] => groupRecentItems(recentItems, recentSort, recentGrouping, spaceNames),
        ],
        recentLoading: [
            (s) => [s.recentTasksLoading, s.conversationHistoryLoading],
            (recentTasksLoading: boolean, conversationHistoryLoading: boolean): boolean =>
                recentTasksLoading || conversationHistoryLoading,
        ],
    }),
    listeners(({ actions, values, cache }) => {
        // Reading a session anywhere in the app clears it, so the rail follows the open session rather than clicks.
        const markOpenSessionRead = (): void => {
            const { location, searchParams } = router.values
            const sessionId = location.pathname.endsWith('/ai') ? searchParams.task : null
            const request = typeof sessionId === 'string' ? sessionReadRequest(values.taskActivity, sessionId) : null
            if (request) {
                actions.markSessionRead(request.marker, request.activityIds)
            }
        }
        return {
            locationChanged: ({ pathname }) => {
                const spaceId = spaceIdForPath(pathname)
                if (spaceId) {
                    actions.spaceVisited(spaceId)
                }
                markOpenSessionRead()
            },
            loadTaskActivitySuccess: markOpenSessionRead,
            loadRecentTasks: () => {
                cache.recentTasksLoadedAt = Date.now()
                actions.loadTaskActivity()
            },
            markSessionRead: async ({ marker, activityIds }) => {
                try {
                    await taskActivityMarkReadCreate(String(values.currentTeamId), { activities: [marker] })
                } catch {
                    actions.markSessionReadFailed(activityIds)
                    toast.error({ title: 'Couldn’t mark this session as read.' })
                }
            },
        }
    }),
    listeners(({ actions, values }) => ({
        setPhoneSection: ({ section }) => {
            posthog.capture('today spaces section picked', { section })
        },
        touchMenuOpened: ({ menu }) => {
            posthog.capture('today touch menu opened', { menu })
        },
        loadPinnedTasksSuccess: ({ pinnedTasks }) =>
            actions.loadPullRequestStates(sessionIdsWithPullRequests(pinnedTasks)),
        loadRecentTasksSuccess: ({ recentTasks }) =>
            actions.loadPullRequestStates(sessionIdsWithPullRequests(recentTasks)),
        // One batched lookup per list.
        loadPullRequestStates: async ({ sessionIds }) => {
            if (!sessionIds.length || !values.currentTeamId) {
                return
            }
            try {
                const response = await tasksSummariesCreate(String(values.currentTeamId), { ids: sessionIds })
                actions.setPullRequestStates(pullRequestStates(response.results))
            } catch {
                // A failed lookup only leaves the chips neutral, so it stays quiet.
            }
        },
        toggleStar: async ({ spaceId, starred }) => {
            try {
                await taskChannelsStarCreate(String(values.currentTeamId), spaceId, { starred })
                actions.loadSpaces()
            } catch {
                toast.error({ title: `Couldn’t ${starred ? 'star' : 'unstar'} this space. Try again.` })
                actions.starFailed(spaceId)
            }
        },
        copySpaceLink: async ({ spaceId }) => {
            const outcome = await writeToClipboard(urls.absolute(urls.currentProject(urls.taskSpace(spaceId))))
            if (outcome === 'copied') {
                toast.success({ title: 'Link copied' })
            } else {
                toast.error({ title: 'Couldn’t copy the link. Copy it from the address bar instead.' })
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        const spaceId = spaceIdForPath(router.values.location.pathname)
        if (spaceId) {
            actions.spaceVisited(spaceId)
        }
        actions.loadSpaces()
        actions.loadPinnedTasks()
        // A disposable rather than a plain afterMount load, so setup runs again on each return to the tab.
        cache.disposables.add(() => {
            if (recentRefreshIsDue(cache.recentTasksLoadedAt)) {
                actions.loadRecentTasks()
            }
            const pollTimer = window.setInterval(() => actions.loadRecentTasks(), RECENT_REFRESH_INTERVAL_MS)
            return () => clearInterval(pollTimer)
        }, 'recentTasksPoll')
    }),
])
