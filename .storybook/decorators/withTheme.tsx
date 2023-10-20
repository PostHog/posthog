import type { Decorator } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

/** Global story decorator that is used by the theming control to
 * switch between themes.
 */
export const withTheme: Decorator = (Story, context) => {
    const theme = context.globals.theme

    // set the body class
    const actualClassState = document.body.classList.contains('posthog-3000')
    const desiredClassState = theme !== 'legacy'

    if (actualClassState !== desiredClassState) {
        if (desiredClassState) {
            document.body.classList.add('posthog-3000')
        } else {
            document.body.classList.remove('posthog-3000')
        }
    }

    // set the feature flag
    const actualFeatureFlagState = window.POSTHOG_APP_CONTEXT!.persisted_feature_flags?.includes(
        FEATURE_FLAGS.POSTHOG_3000
    )
    const desiredFeatureFlagState = theme !== 'legacy'

    if (actualFeatureFlagState !== desiredFeatureFlagState) {
        const currentFlags = window.POSTHOG_APP_CONTEXT!.persisted_feature_flags || []
        if (desiredFeatureFlagState) {
            window.POSTHOG_APP_CONTEXT!.persisted_feature_flags = [...currentFlags, FEATURE_FLAGS.POSTHOG_3000]
        } else {
            window.POSTHOG_APP_CONTEXT!.persisted_feature_flags = currentFlags.filter(
                (f) => f !== FEATURE_FLAGS.POSTHOG_3000
            )
        }
    }

    // set the theme
    document.body.setAttribute('theme', theme === 'dark' ? 'dark' : 'light')

    return <Story />
}
