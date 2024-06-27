import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import type { themeLogicType } from './themeLogicType'
import { Theme, themes } from './themes'

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    connect({
        values: [userLogic, ['themeMode'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        syncDarkModePreference: (darkModePreference: boolean) => ({ darkModePreference }),
        setTheme: (theme: string | null) => ({ theme }),
        reload: true,
    }),
    reducers({
        darkModeSystemPreference: [
            window.matchMedia('(prefers-color-scheme: dark)').matches,
            {
                syncDarkModePreference: (_, { darkModePreference }) => darkModePreference,
            },
        ],
        selectedTheme: [
            null as string | null,
            { persist: true },
            {
                setTheme: (_, { theme }) => theme,
            },
        ],
        reloadCount: [
            0,
            {
                reload: (state) => state + 1,
            },
        ],
    }),
    selectors({
        theme: [
            (s) => [s.selectedTheme, s.featureFlags],
            (selectedTheme, featureFlags): Theme | null => {
                const flagVariant = featureFlags[FEATURE_FLAGS.THEME]
                return (
                    (selectedTheme ? themes.find((theme) => theme.id === selectedTheme) : null) ??
                    (typeof flagVariant === 'string' ? themes.find((theme) => theme.id === flagVariant) : null) ??
                    null
                )
            },
        ],
        isDarkModeOn: [
            (s) => [s.themeMode, s.darkModeSystemPreference, sceneLogic.selectors.sceneConfig, s.theme, s.reloadCount],
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            (themeMode, darkModeSystemPreference, sceneConfig, theme, reloadCount) => {
                // dark mode in storybook
                if (
                    typeof window !== 'undefined' &&
                    window.document &&
                    document.body.classList.contains('storybook-test-runner') &&
                    document.body.getAttribute('theme') == 'dark'
                ) {
                    return true
                }

                if (theme) {
                    return !!theme?.dark
                }
                // NOTE: Unauthenticated users always get the light mode until we have full support across onboarding flows
                if (
                    sceneConfig?.layout === 'plain' ||
                    sceneConfig?.allowUnauthenticated ||
                    sceneConfig?.onlyUnauthenticated
                ) {
                    return false
                }

                return themeMode === 'system' ? darkModeSystemPreference : themeMode === 'dark'
            },
        ],
    }),
    events(({ cache, actions }) => ({
        afterMount() {
            cache.prefersColorSchemeMedia = window.matchMedia('(prefers-color-scheme: dark)')
            cache.onPrefersColorSchemeChange = (e: MediaQueryListEvent) => actions.syncDarkModePreference(e.matches)
            cache.prefersColorSchemeMedia.addEventListener('change', cache.onPrefersColorSchemeChange)
            if (
                typeof window !== 'undefined' &&
                window.document &&
                document.body.classList.contains('storybook-test-runner') &&
                document.body.getAttribute('theme') == 'dark'
            ) {
                ;(window as any).__reloadThemeLogic = () => actions.reload()
            }
        },
        beforeUnmount() {
            cache.prefersColorSchemeMedia.removeEventListener('change', cache.onPrefersColorSchemeChange)
        },
    })),
])
