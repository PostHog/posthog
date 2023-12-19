import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import type { themeLogicType } from './themeLogicType'

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    connect({
        values: [userLogic, ['user']],
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
            (s) => [s.user, s.darkModeSystemPreference, sceneLogic.selectors.sceneConfig],
            (user, darkModeSystemPreference, sceneConfig) => {
                // NOTE: Unauthenticated users always get the light mode until we have full support across onboarding flows
                if (
                    sceneConfig?.layout === 'plain' ||
                    sceneConfig?.allowUnauthenticated ||
                    sceneConfig?.onlyUnauthenticated
                ) {
                    return false
                }

                // User-saved preference is used when set, oterwise we fall back to the system value
                return user?.theme_mode ? user.theme_mode === 'dark' : darkModeSystemPreference
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
