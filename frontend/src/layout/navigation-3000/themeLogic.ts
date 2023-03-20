import { actions, events, kea, path, reducers, selectors } from 'kea'

import type { themeLogicType } from './themeLogicType'

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    actions({
        toggleTheme: true,
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
            (s) => [s.darkModeSavedPreference, s.darkModeSystemPreference],
            (darkModeSavedPreference, darkModeSystemPreference) => {
                return darkModeSavedPreference ?? darkModeSystemPreference
            },
        ],
        isThemeSyncedWithSystem: [
            (s) => [s.darkModeSavedPreference],
            (darkModeSavedPreference) => {
                return darkModeSavedPreference === null
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
