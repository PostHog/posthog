import type { Parameters } from '@storybook/react'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'

/** Copies a settings story with the new navigation on, which renders the settings in quill. */
export function withTodayRailNav<T extends { parameters?: Parameters }>(story: T): T {
    const featureFlags: string[] = Array.isArray(story.parameters?.featureFlags)
        ? story.parameters.featureFlags
        : STORYBOOK_FEATURE_FLAGS

    return {
        ...story,
        parameters: {
            ...story.parameters,
            featureFlags: [...featureFlags, FEATURE_FLAGS.TODAY_RAIL_NAV],
        },
    }
}
