import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import type { aiFirstHomepageLogicType } from './aiFirstHomepageLogicType'

export type HomepageMode = 'idle' | 'search' | 'ai'
export type AnimationPhase = 'idle' | 'moving' | 'separator' | 'content'

export interface LayoutState {
    mode: HomepageMode
    animationPhase: AnimationPhase
}

export const aiFirstHomepageLogic = kea<aiFirstHomepageLogicType>([
    path(['scenes', 'project-homepage', 'ai-first', 'aiFirstHomepageLogic']),

    actions({
        submitQuery: (mode: 'search' | 'ai') => ({ mode }),
        setQuery: (query: string) => ({ query }),
        setAnimationPhase: (phase: AnimationPhase) => ({ phase }),
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
    }),

    selectors({
        mode: [(s) => [s.layoutState], (layoutState): HomepageMode => layoutState.mode],
        animationPhase: [(s) => [s.layoutState], (layoutState): AnimationPhase => layoutState.animationPhase],
    }),

    listeners(({ actions, values }) => ({
        submitQuery: async (_, breakpoint) => {
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

            if (urlMode === 'idle' && values.mode !== 'idle') {
                actions.returnToIdle()
            } else if (urlMode !== 'idle' && urlMode !== values.mode) {
                actions.setQuery(urlQuery)
                actions.submitQuery(urlMode as 'search' | 'ai')
            } else if (urlQuery !== values.query) {
                actions.setQuery(urlQuery)
            }
        },
    })),

    afterMount(({ actions }) => {
        const { searchParams } = router.values
        const urlMode = (searchParams.mode as HomepageMode) || 'idle'
        const urlQuery = (searchParams.q as string) || ''

        if (urlMode !== 'idle' && urlQuery) {
            actions.setQuery(urlQuery)
            actions.submitQuery(urlMode as 'search' | 'ai')
        }
    }),
])
