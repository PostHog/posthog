import { useFeatureFlags } from '~/mocks/browser'
import type { Decorator } from '@storybook/react'

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
        useFeatureFlags(parameters.featureFlags)
    }

    return <Story />
}
