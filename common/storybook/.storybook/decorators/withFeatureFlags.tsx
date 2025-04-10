import { setFeatureFlags } from '~/mocks/browser'
import type { Decorator } from '@storybook/react'

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
 *     featureFlags: ['hogql'], // add flags here
 *   },
 * } as ComponentMeta<typeof MyComponent>
 * ```
 */
export const withFeatureFlags: Decorator = (Story, { parameters }) => {
    if (parameters.featureFlags) {
        setFeatureFlags(parameters.featureFlags)
    }

    return <Story />
}
