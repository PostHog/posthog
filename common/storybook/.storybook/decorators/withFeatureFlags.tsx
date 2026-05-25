import type { Decorator } from '@storybook/react'

import { setFeatureFlags } from '~/mocks/browser'

declare module '@storybook/types' {
    interface Parameters {
        featureFlags?: string[] | Record<string, string | boolean>
    }
}

/** Global story decorator that allows setting feature flags.
 *
 * Boolean flags (default):
 * ```ts
 * parameters: {
 *   featureFlags: [FEATURE_FLAGS.HOGQL],
 * }
 * ```
 *
 * Multivariate flags (set a specific variant):
 * ```ts
 * parameters: {
 *   featureFlags: { [FEATURE_FLAGS.MY_EXPERIMENT]: 'test' },
 * }
 * ```
 *
 * The decorator both populates `POSTHOG_APP_CONTEXT.persisted_feature_flags`
 * (for fresh mounts) and dispatches `featureFlagLogic.actions.setFeatureFlags`
 * (so already-mounted consumers react in the same tick the story renders).
 */
export const withFeatureFlags: Decorator = (Story, { parameters: { featureFlags = [] } }) => {
    setFeatureFlags(featureFlags)

    return <Story />
}
