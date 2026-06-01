import { DecoratorFunction } from '@storybook/types'
import { rest, setupWorker } from 'msw'

import { handlers } from '~/mocks/handlers'
import { MockSignature, Mocks, mocksToHandlers } from '~/mocks/utils'
import type { AppContext } from '~/types'

// Default handlers ensure no request is unhandled by msw
export const worker: ReturnType<typeof setupWorker> = setupWorker(...handlers)

export const useStorybookMocks = (mocks: Mocks): void => worker.use(...mocksToHandlers(mocks))

export const mswDecorator = (mocks: Mocks): DecoratorFunction<any> => {
    return function StoryMock(Story, { parameters }): JSX.Element {
        // merge the default mocks provided in `preview.tsx` with any provided by the story
        // allow the story to override defaults
        const mergedMocks: Mocks = {}
        const restKeys = Object.keys(rest) as Array<keyof typeof rest>
        for (const restMethod of restKeys) {
            mergedMocks[restMethod] = {}
            const storyMethodMocks = (parameters.msw?.mocks?.[restMethod] || {}) as Record<string, MockSignature>
            // Ensure trailing slashes to avoid default handlers accidentally overshadowing story mocks
            for (const [path, handler] of Object.entries(storyMethodMocks)) {
                const cleanedPath = path.replace(/\/?$/, '/')
                mergedMocks[restMethod][cleanedPath] = handler
            }
            for (const [path, handler] of Object.entries(mocks?.[restMethod] || {})) {
                const cleanedPath = path.replace(/\/?$/, '/')
                mergedMocks[restMethod][cleanedPath] = handler
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
