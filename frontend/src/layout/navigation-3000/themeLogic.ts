import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import type { themeLogicType } from './themeLogicType'

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    connect({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['user']],
    }),
    actions({
        syncDarkModePreference: (darkModePreference: boolean) => ({ darkModePreference }),
    }),
    reducers({
        darkModeSystemPreference: [
            window.matchMedia('(prefers-color-scheme: dark)').matches,
            {
                syncDarkModePreference: (_, { darkModePreference }) => darkModePreference,
            },
        ],
    }),
    selectors({
        isDarkModeOn: [
            (s) => [s.user, s.darkModeSystemPreference, s.featureFlags, sceneLogic.selectors.sceneConfig],
            (user, darkModeSystemPreference, featureFlags, sceneConfig) => {
                // NOTE: Unauthenticated users always get the light mode until we have full support across onboarding flows
                if (
                    sceneConfig?.layout === 'plain' ||
                    sceneConfig?.allowUnauthenticated ||
                    sceneConfig?.onlyUnauthenticated
                ) {
                    return false
                }
                // Dark mode is a PostHog 3000 feature
                // User-saved preference is used when set, oterwise we fall back to the system value
                return featureFlags[FEATURE_FLAGS.POSTHOG_3000]
                    ? user?.theme_mode
                        ? user.theme_mode === 'dark'
                        : darkModeSystemPreference
                    : false
            },
        ],
    }),
    events(({ cache, actions }) => ({
        afterMount() {
            cache.prefersColorSchemeMedia = window.matchMedia('(prefers-color-scheme: dark)')
            cache.onPrefersColorSchemeChange = (e: MediaQueryListEvent) => actions.syncDarkModePreference(e.matches)
            cache.prefersColorSchemeMedia.addEventListener('change', cache.onPrefersColorSchemeChange)
        },
        beforeUnmount() {
            cache.prefersColorSchemeMedia.removeEventListener('change', cache.onPrefersColorSchemeChange)
        },
    })),
])
