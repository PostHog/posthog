import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { userLogic } from 'scenes/userLogic'

import type { themeLogicType } from './themeLogicType'

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    connect({
        values: [userLogic, ['userThemeMode']],
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
            (s) => [s.userThemeMode, s.darkModeSystemPreference],
            (userThemeMode, darkModeSystemPreference) => {
                return userThemeMode === 'system' ? darkModeSystemPreference : userThemeMode === 'dark'
            },
        ],
    }),
    subscriptions({
        isDarkModeOn: (isDarkModeOn) => {
            document.cookie = `theme=${isDarkModeOn ? 'dark' : 'light'}; Path=/; Domain=posthog.com`
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
