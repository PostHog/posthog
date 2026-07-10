import type { Decorator } from '@storybook/react'

import { setFeatureFlags } from '~/mocks/browser'

declare module 'storybook/internal/types' {
    interface Parameters {
        featureFlags?: string[] | Record<string, string | boolean>
    }
}

/** Global story decorator that allows setting feature flags.
 *
 * Boolean flags (just "on") — pass an array:
 * ```ts
 * parameters: { featureFlags: [FEATURE_FLAGS.HOGQL] }
 * ```
 *
 * Multivariate flags — pin a specific variant with the record form:
 * ```ts
 * parameters: { featureFlags: { [FEATURE_FLAGS.THEME_OVERRIDE]: 'intent_plus' } }
 * ```
 */
export const withFeatureFlags: Decorator = (Story, { parameters: { featureFlags = [] } }) => {
    setFeatureFlags(featureFlags)

    return <Story />
}
