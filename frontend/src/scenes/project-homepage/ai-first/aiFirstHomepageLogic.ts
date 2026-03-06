import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { maxLogic } from 'scenes/max/maxLogic'
import { urls } from 'scenes/urls'

import type { aiFirstHomepageLogicType } from './aiFirstHomepageLogicType'
import { HOMEPAGE_TAB_ID } from './constants'

export type HomepageMode = 'idle' | 'search' | 'ai'
export type AnimationPhase = 'idle' | 'moving' | 'separator' | 'content'

export interface LayoutState {
    mode: HomepageMode
    animationPhase: AnimationPhase
}

export const aiFirstHomepageLogic = kea<aiFirstHomepageLogicType>([
    path(['scenes', 'project-homepage', 'ai-first', 'aiFirstHomepageLogic']),

    connect(() => ({
        values: [maxLogic({ tabId: HOMEPAGE_TAB_ID }), ['threadLogicKey']],
        actions: [maxLogic({ tabId: HOMEPAGE_TAB_ID }), ['openConversation', 'startNewConversation']],
    })),

    actions({
        submitQuery: (mode: 'search' | 'ai') => ({ mode }),
        setQuery: (query: string) => ({ query }),
        setAnimationPhase: (phase: AnimationPhase) => ({ phase }),
        setHoveredSuggestion: (suggestion: string | null) => ({ suggestion }),
        returnToIdle: true,
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
        hoveredSuggestion: [
            null as string | null,
            {
                setHoveredSuggestion: (_, { suggestion }) => suggestion,
            },
        ],
    }),

    selectors({
        mode: [(s) => [s.layoutState], (layoutState): HomepageMode => layoutState.mode],
        animationPhase: [(s) => [s.layoutState], (layoutState): AnimationPhase => layoutState.animationPhase],
        placeholder: [
            (s) => [s.hoveredSuggestion],
            (hoveredSuggestion): string => hoveredSuggestion ?? 'What can I help you with?',
        ],
    }),

    listeners(({ actions, values }) => ({
        submitQuery: async ({ mode }, breakpoint) => {
            if (mode === 'ai') {
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
        returnToIdle: () => {
            return [urls.projectHomepage(), {}, undefined, { replace: true }]
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
                }
                actions.submitQuery('ai')
            } else if (urlMode === 'search' && values.mode !== 'search') {
                actions.setQuery(urlQuery)
                actions.submitQuery('search')
            } else if (urlMode === 'search' && urlQuery !== values.query) {
                actions.setQuery(urlQuery)
            }
        },
    })),

    afterMount(({ actions }) => {
        const { searchParams } = router.values
        const urlMode = (searchParams.mode as HomepageMode) || 'idle'
        const urlQuery = (searchParams.q as string) || ''
        const urlChat = (searchParams.chat as string) || ''

        if (urlMode === 'ai') {
            if (urlChat) {
                actions.openConversation(urlChat)
            }
            actions.submitQuery('ai')
        } else if (urlMode === 'search' && urlQuery) {
            actions.setQuery(urlQuery)
            actions.submitQuery('search')
        }
    }),
])
