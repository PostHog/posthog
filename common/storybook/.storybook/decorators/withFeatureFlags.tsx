import type { Decorator } from '@storybook/react'

import { setFeatureFlags } from '~/mocks/browser'

declare module '@storybook/types' {
    interface Parameters {
        featureFlags?: string[]
    }
}

/** Global story decorator that allows setting feature flags.
 *
 * ```ts
 * export default {
 *   title: 'My story',
 *   component: MyComponent,
 *   parameters: {
 *     featureFlags: [FEATURE_FLAGS.HOGQL], // add flags here
 *   },
 * } as ComponentMeta<typeof MyComponent>
 * ```
 */
export const withFeatureFlags: Decorator = (Story, { parameters: { featureFlags = [] } }) => {
    setFeatureFlags(featureFlags)

    return <Story />
}
