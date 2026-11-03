import type { Decorator } from '@storybook/react'
import { setupWorker } from 'msw/browser'

import { handlers, toPaginatedResponse } from '~/mocks/handlers'
import { HTTP_METHODS, MockSignature, Mocks, mocksToHandlers } from '~/mocks/utils'
import type { AppContext } from '~/types'

// Stories start with the products new users get starred, so the sidebar shows those instead of the
// whole product catalog. A story that mocks shortcuts itself still wins.
const storybookDefaultMocks: Mocks = {
    get: {
        '/api/environments/:team_id/file_system_shortcut/': toPaginatedResponse([
            { id: 'starred-dashboards', path: 'Dashboards', type: 'dashboard', order: 1 },
            { id: 'starred-product-analytics', path: 'Product analytics', type: 'product_analytics', order: 2 },
            { id: 'starred-web-analytics', path: 'Web analytics', type: 'web_analytics', order: 3 },
            { id: 'starred-mcp-analytics', path: 'MCP analytics', type: 'mcp_analytics', order: 4 },
        ]),
    },
}

// Default handlers ensure no request is unhandled by msw. Handlers listed first take precedence.
export const worker: ReturnType<typeof setupWorker> = setupWorker(
    ...mocksToHandlers(storybookDefaultMocks),
    ...handlers
)

export const useStorybookMocks = (mocks: Mocks): void => worker.use(...mocksToHandlers(mocks))

export const mswDecorator = (mocks: Mocks): Decorator<any> => {
    return function StoryMock(Story, { parameters }): JSX.Element {
        // merge the default mocks provided in `preview.tsx` with any provided by the story
        // allow the story to override defaults
        const mergedMocks: Mocks = {}
        for (const method of HTTP_METHODS) {
            mergedMocks[method] = {}
            const storyMethodMocks = (parameters.msw?.mocks?.[method] || {}) as Record<string, MockSignature>
            // Ensure trailing slashes to avoid default handlers accidentally overshadowing story mocks
            for (const [path, handler] of Object.entries(storyMethodMocks)) {
                const cleanedPath = path.replace(/\/?$/, '/')
                mergedMocks[method][cleanedPath] = handler
            }
            for (const [path, handler] of Object.entries(mocks?.[method] || {})) {
                const cleanedPath = path.replace(/\/?$/, '/')
                mergedMocks[method][cleanedPath] = handler
            }
        }
        useStorybookMocks(mergedMocks)
        return <Story />
    }
}

/**
 * Set feature flags for a story.
 *
 * - `string[]` — flags that are simply **on** (each maps to `true`).
 * - `Record<string, string | boolean>` — pin specific **multivariate** variants
 *   (e.g. `{ 'my-flag': 'test_b' }`); mix with booleans freely.
 *
 * Both forms are written straight to `persisted_feature_flags`, the baseline
 * `featureFlagLogic` reads on mount and always merges (see `getPersistedFeatureFlags`).
 * That's what makes a pinned variant survive the empty `onFeatureFlags` callback
 * posthog-js fires on load — no need to disable flags or touch preflight.
 */
export const setFeatureFlags = (featureFlags: string[] | Record<string, string | boolean>): void => {
    const appContext = (window as any).POSTHOG_APP_CONTEXT as AppContext
    appContext.persisted_feature_flags = featureFlags
}
