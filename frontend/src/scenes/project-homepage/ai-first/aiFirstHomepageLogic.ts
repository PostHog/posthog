import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { maxLogic } from 'scenes/max/maxLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { sceneLogic } from '~/scenes/sceneLogic'
import { emptySceneParams } from '~/scenes/scenes'
import { Scene, SceneTab } from '~/scenes/sceneTypes'
import { DashboardBasicType } from '~/types'

import type { aiFirstHomepageLogicType } from './aiFirstHomepageLogicType'
import { HOMEPAGE_TAB_ID } from './constants'

export type HomepageMode = 'idle' | 'search' | 'ai'
export type AnimationPhase = 'idle' | 'moving' | 'separator' | 'content'

export interface LayoutState {
    mode: HomepageMode
    animationPhase: AnimationPhase
}

export type HomepageGridItemKind = 'dashboard' | 'recent' | 'starred'

export interface HomepageGridItem {
    id: string
    /** The raw FileSystemEntry ID, used for shortcut deletion. */
    entryId?: string
    /** The original FileSystemEntry, used for adding to starred. */
    entry?: FileSystemEntry
    label: string
    icon?: React.ReactNode
    href?: string
    kind: HomepageGridItemKind
    itemType?: string | null
}

const GRID_LIMIT = 5

const PREVIOUS_HOMEPAGE_KEY = 'ai-first-previous-homepage'

function getStorageKey(): string {
    const teamId = teamLogic.findMounted()?.values.currentTeamId ?? 'null'
    return `${PREVIOUS_HOMEPAGE_KEY}-${teamId}`
}

function loadPreviousHomepage(): SceneTab | null {
    try {
        const stored = localStorage.getItem(getStorageKey())
        return stored ? JSON.parse(stored) : null
    } catch {
        return null
    }
}

function savePreviousHomepage(tab: SceneTab | null): void {
    const key = getStorageKey()
    if (tab) {
        localStorage.setItem(key, JSON.stringify(tab))
    } else {
        localStorage.removeItem(key)
    }
}

export const aiFirstHomepageLogic = kea<aiFirstHomepageLogicType>([
    path(['scenes', 'project-homepage', 'ai-first', 'aiFirstHomepageLogic']),

    connect(() => ({
        values: [
            maxLogic({ tabId: HOMEPAGE_TAB_ID }),
            ['threadLogicKey', 'conversationId'],
            teamLogic,
            ['currentTeam'],
            sceneLogic,
            ['homepage'],
            dashboardsModel,
            ['pinnedDashboards', 'dashboardsLoading'],
            recentItemsModel,
            ['recents as cachedRecents', 'recentsLoading'],
            projectTreeDataLogic,
            ['shortcutData as cachedStarred'],
        ],
        actions: [
            maxLogic({ tabId: HOMEPAGE_TAB_ID }),
            ['openConversation', 'startNewConversation', 'setQuestion'],
            sceneLogic,
            ['setHomepage'],
        ],
    })),

    actions({
        submitQuery: (mode: 'search' | 'ai') => ({ mode }),
        enterAiMode: (trigger: string) => ({ trigger }),
        setQuery: (query: string) => ({ query }),
        setAnimationPhase: (phase: AnimationPhase) => ({ phase }),
        returnToIdle: true,
        setPreviousHomepage: (tab: SceneTab | null) => ({ tab }),
        revertToPreviousHomepage: true,
    }),

    reducers({
        // Single reducer for mode + phase so transitions are atomic
        layoutState: [
            { mode: 'idle', animationPhase: 'idle' } as LayoutState,
            {
                submitQuery: (state, { mode }): LayoutState => {
                    // Re-submit in the same mode with content already visible — no-op
                    if (state.mode === mode && state.animationPhase === 'content') {
                        return state
                    }
                    return { mode, animationPhase: 'moving' }
                },
                enterAiMode: (state): LayoutState => {
                    if (state.mode === 'ai') {
                        return state
                    }
                    return { mode: 'ai', animationPhase: 'moving' }
                },
                setAnimationPhase: (state, { phase }): LayoutState => ({
                    ...state,
                    animationPhase: phase,
                }),
                returnToIdle: (): LayoutState => ({ mode: 'idle', animationPhase: 'idle' }),
            },
        ],
        query: [
            '',
            {
                setQuery: (_, { query }) => query,
                returnToIdle: () => '',
            },
        ],
        threadStarted: [
            false,
            {
                submitQuery: (_, { mode }) => mode === 'ai',
                returnToIdle: () => false,
            },
        ],
        previousHomepage: [
            null as SceneTab | null,
            {
                setPreviousHomepage: (_, { tab }) => tab,
            },
        ],
    }),

    selectors({
        recentItems: [
            (s) => [s.cachedRecents],
            (cachedRecents): FileSystemEntry[] => cachedRecents.slice(0, GRID_LIMIT),
        ],
        recentItemsLoading: [(s) => [s.recentsLoading], (recentsLoading): boolean => recentsLoading],
        starredItems: [
            (s) => [s.cachedStarred],
            (cachedStarred): FileSystemEntry[] => cachedStarred.filter((e) => e.type !== 'folder').slice(0, GRID_LIMIT),
        ],
        starredItemsLoading: [() => [], (): boolean => false],
        mode: [(s) => [s.layoutState], (layoutState): HomepageMode => layoutState.mode],
        animationPhase: [(s) => [s.layoutState], (layoutState): AnimationPhase => layoutState.animationPhase],
        pinnedDashboardItems: [
            (s) => [s.pinnedDashboards],
            (pinnedDashboards): HomepageGridItem[] =>
                pinnedDashboards.slice(0, GRID_LIMIT).map(
                    (d: DashboardBasicType): HomepageGridItem => ({
                        id: `dashboard-${d.id}`,
                        label: d.name || `Dashboard ${d.id}`,
                        href: urls.dashboard(d.id),
                        kind: 'dashboard',
                        itemType: 'dashboard',
                    })
                ),
        ],
        gridItems: [
            (s) => [s.pinnedDashboardItems, s.recentItems, s.starredItems],
            (pinnedDashboardItems, recentItems, starredItems): HomepageGridItem[] => {
                const toGridItem = (entry: FileSystemEntry, kind: HomepageGridItemKind): HomepageGridItem => {
                    const name = splitPath(entry.path).pop()
                    return {
                        id: `${kind}-${entry.id}`,
                        entryId: entry.id,
                        entry,
                        label: name ? unescapePath(name) : entry.path,
                        href: entry.href || '#',
                        kind,
                        itemType: entry.type ?? null,
                    }
                }
                return [
                    ...pinnedDashboardItems,
                    ...recentItems.map((e: FileSystemEntry) => toGridItem(e, 'recent')),
                    ...starredItems.map((e: FileSystemEntry) => toGridItem(e, 'starred')),
                ]
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        submitQuery: async ({ mode }, breakpoint) => {
            if (mode === 'ai' && !values.conversationId) {
                actions.startNewConversation()
            }

            // Reducer kept phase as 'content' for same-mode re-submits — nothing to animate
            if (values.animationPhase === 'content') {
                return
            }

            await breakpoint(300)
            actions.setAnimationPhase('separator')

            await breakpoint(200)
            actions.setAnimationPhase('content')
        },
        enterAiMode: async ({ trigger }, breakpoint) => {
            // Animate into AI mode without starting a conversation
            await breakpoint(300)
            actions.setAnimationPhase('separator')

            await breakpoint(200)
            actions.setAnimationPhase('content')

            // Set the trigger character after animation so the slash menu doesn't appear mid-transition
            if (trigger) {
                actions.setQuestion(trigger)
            }
        },
        setPreviousHomepage: ({ tab }) => {
            savePreviousHomepage(tab)
        },
        revertToPreviousHomepage: () => {
            const prev = values.previousHomepage
            if (prev) {
                actions.setHomepage(prev)
                actions.setPreviousHomepage(null)
                router.actions.push(prev.pathname || '/', prev.search || '', prev.hash || '')
            }
        },
    })),

    actionToUrl(({ values }) => ({
        submitQuery: () => {
            const { mode, query } = values
            if (mode === 'ai') {
                return [
                    urls.projectHomepage(),
                    { mode, chat: values.threadLogicKey || undefined },
                    undefined,
                    { replace: false },
                ]
            }
            return [urls.projectHomepage(), { mode, q: query || undefined }, undefined, { replace: false }]
        },
        enterAiMode: () => {
            return [urls.projectHomepage(), { mode: 'ai' }, undefined, { replace: false }]
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.projectHomepage()]: (_, searchParams) => {
            const urlMode = (searchParams.mode as HomepageMode) || 'idle'
            const urlQuery = (searchParams.q as string) || ''
            const urlChat = (searchParams.chat as string) || ''

            if (urlMode === 'idle' && values.mode !== 'idle') {
                actions.returnToIdle()
            } else if (urlMode === 'ai' && values.mode !== 'ai') {
                if (urlChat) {
                    actions.openConversation(urlChat)
                    actions.submitQuery('ai')
                } else {
                    actions.enterAiMode('')
                }
            } else if (urlMode === 'search' && values.mode !== 'search') {
                actions.setQuery(urlQuery)
                actions.submitQuery('search')
            } else if (urlMode === 'search' && urlQuery !== values.query) {
                actions.setQuery(urlQuery)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        // Capture the previous homepage on first visit so we can revert later
        const stored = loadPreviousHomepage()
        if (stored) {
            actions.setPreviousHomepage(stored)
        } else {
            // First time on AI-first homepage — snapshot what the user would have seen before
            const currentHomepage = values.homepage
            if (currentHomepage) {
                // User had a custom homepage set
                actions.setPreviousHomepage(currentHomepage)
            } else {
                // No custom homepage — they would have seen the primary dashboard or search
                const dashboardId = values.currentTeam?.primary_dashboard
                if (dashboardId) {
                    actions.setPreviousHomepage({
                        id: `homepage-dashboard-${dashboardId}`,
                        pathname: urls.dashboard(dashboardId),
                        search: '',
                        hash: '',
                        title: 'Default dashboard',
                        iconType: 'dashboard',
                        active: false,
                        pinned: true,
                        sceneId: Scene.Dashboard,
                        sceneKey: `dashboard-${dashboardId}`,
                        sceneParams: emptySceneParams,
                    })
                }
                // If no dashboard either, previousHomepage stays null — no revert button shown
            }
        }

        const { searchParams } = router.values
        const urlMode = (searchParams.mode as HomepageMode) || 'idle'
        const urlQuery = (searchParams.q as string) || ''
        const urlChat = (searchParams.chat as string) || ''

        if (urlMode === 'ai') {
            if (urlChat) {
                actions.openConversation(urlChat)
                actions.submitQuery('ai')
            } else {
                actions.enterAiMode('')
            }
        } else if (urlMode === 'search' && urlQuery) {
            actions.setQuery(urlQuery)
            actions.submitQuery('search')
        }
    }),
])
