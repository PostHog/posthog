import { DecoratorFunction } from '@storybook/types'
import { rest, setupWorker } from 'msw'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { handlers } from '~/mocks/handlers'
import { MockSignature, Mocks, mocksToHandlers } from '~/mocks/utils'

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
 * Storybook-only feature-flag mock helper. NOT for production use.
 *
 * Accepts either `string[]` (boolean flags — each entry becomes `{key: true}`)
 * or `Record<string, string | boolean>` (multivariate — set specific variants).
 *
 * - Writes the flag keys to `POSTHOG_APP_CONTEXT.persisted_feature_flags`
 *   (the production-shaped `string[]` field that fresh kea logic mounts read).
 * - Dispatches the full variants record through `featureFlagLogic.actions.setFeatureFlags`
 *   so already-mounted consumers update before the visual-regression runner
 *   captures the snapshot. The kea reducer overwrites state on each dispatch
 *   so empty input from a story with no `featureFlags` parameter resets state
 *   for the next story.
 *
 * `featureFlagLogic` is mounted but never unmounted — that is intentional in
 * the storybook iframe lifecycle, where the logic should stick around for
 * the duration of the session and receive successive dispatches.
 */
export const setFeatureFlags = (featureFlags: string[] | Record<string, string | boolean>): void => {
    const variants: Record<string, string | boolean> = Array.isArray(featureFlags)
        ? Object.fromEntries(featureFlags.map((f) => [f, true]))
        : featureFlags
    const keys = Object.keys(variants)
    ;(window as any).POSTHOG_APP_CONTEXT.persisted_feature_flags = keys
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags(keys, variants)
}
