import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import type { aiFirstHomepageLogicType } from './aiFirstHomepageLogicType'

export type HomepageMode = 'idle' | 'search' | 'ai'
export type AnimationPhase = 'idle' | 'moving' | 'separator' | 'content'

export const aiFirstHomepageLogic = kea<aiFirstHomepageLogicType>([
    path(['scenes', 'project-homepage', 'ai-first', 'aiFirstHomepageLogic']),

    actions({
        setMode: (mode: HomepageMode) => ({ mode }),
        setQuery: (query: string) => ({ query }),
        submitQuery: (mode: 'search' | 'ai') => ({ mode }),
        setAnimationPhase: (phase: AnimationPhase) => ({ phase }),
        returnToIdle: true,
    }),

    reducers({
        mode: [
            'idle' as HomepageMode,
            {
                setMode: (_, { mode }) => mode,
                returnToIdle: () => 'idle' as HomepageMode,
            },
        ],
        query: [
            '',
            {
                setQuery: (_, { query }) => query,
                returnToIdle: () => '',
            },
        ],
        animationPhase: [
            'idle' as AnimationPhase,
            {
                setAnimationPhase: (_, { phase }) => phase,
                returnToIdle: () => 'idle' as AnimationPhase,
            },
        ],
    }),

    listeners(({ actions }) => ({
        submitQuery: async ({ mode }, breakpoint) => {
            actions.setMode(mode)
            actions.setAnimationPhase('moving')

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
