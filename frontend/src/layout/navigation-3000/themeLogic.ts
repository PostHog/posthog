import { actions, events, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { themeLogicType } from './themeLogicType'
import { sceneLogic } from 'scenes/sceneLogic'

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    actions({
        toggleTheme: true,
        overrideTheme: (darkModePreference: boolean) => ({ darkModePreference }),
        syncDarkModePreference: (darkModePreference: boolean) => ({ darkModePreference }),
    }),
    reducers({
        darkModeSavedPreference: [
            null as boolean | null,
            {
                persist: true,
            },
            {
                toggleTheme: (state) => (state === false ? null : !state),
                overrideTheme: (_, { darkModePreference }) => darkModePreference,
            },
        ],
        darkModeSystemPreference: [
            window.matchMedia('(prefers-color-scheme: dark)').matches,
            {
                syncDarkModePreference: (_, { darkModePreference }) => darkModePreference,
            },
        ],
    }),
    selectors({
        isDarkModeOn: [
            (s) => [
                s.darkModeSavedPreference,
                s.darkModeSystemPreference,
                featureFlagLogic.selectors.featureFlags,
                sceneLogic.selectors.sceneConfig,
            ],
            (darkModeSavedPreference, darkModeSystemPreference, featureFlags, sceneConfig) => {
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
                    ? darkModeSavedPreference ?? darkModeSystemPreference
                    : false
            },
        ],
        isThemeSyncedWithSystem: [
            (s) => [s.darkModeSavedPreference],
            (darkModeSavedPreference) => {
                return darkModeSavedPreference === null
            },
        ],
    }),
    subscriptions({
        isDarkModeOn: (isDarkModeOn) => {
            document.body.setAttribute('theme', isDarkModeOn ? 'dark' : 'light')
        },
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
