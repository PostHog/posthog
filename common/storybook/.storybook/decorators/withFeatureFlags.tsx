import { setFeatureFlags } from '~/mocks/browser'
import type { Decorator } from '@storybook/react'

declare module '@storybook/types' {
    interface Parameters {
        featureFlags?: string[]
    }
}

/** Sync with posthog/settings/feature_flags.py */
const PERSISTED_FEATURE_FLAGS = [
    'simplify-actions',
    'historical-exports-v2',
    'ingestion-warnings-enabled',
    'persons-hogql-query',
    'datanode-concurrency-limit',
    'session-table-property-filters',
    'query-async',
    'artificial-hog',
]

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
export const withFeatureFlags: Decorator = (Story, { parameters }) => {
    setFeatureFlags([...PERSISTED_FEATURE_FLAGS, ...(parameters.featureFlags || [])])

    return <Story />
}
