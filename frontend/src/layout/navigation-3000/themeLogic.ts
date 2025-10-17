import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import type { themeLogicType } from './themeLogicType'
import { Theme, themes } from './themes'

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    connect(() => ({
        logic: [sceneLogic],
        values: [userLogic, ['themeMode'], featureFlagLogic, ['featureFlags']],
    })),

    actions({
        syncDarkModePreference: (darkModePreference: boolean) => ({ darkModePreference }),
        setTheme: (theme: string | null) => ({ theme }),
        saveCustomCss: true,
        setPersistedCustomCss: (css: string | null) => ({ css }),
        setPreviewingCustomCss: (css: string | null) => ({ css }),
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
        persistedCustomCss: [
            null as string | null,
            { persist: true },
            {
                setPersistedCustomCss: (_, { css }) => css,
            },
        ],
        previewingCustomCss: [
            null as string | null,
            { persist: true },
            {
                setPreviewingCustomCss: (_, { css }) => css,
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
        customCssEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.CUSTOM_CSS_THEMES],
        ],
        customCss: [
            (s) => [s.persistedCustomCss, s.previewingCustomCss],
            (persistedCustomCss, previewingCustomCss): string | null => previewingCustomCss || persistedCustomCss,
        ],
        isDarkModeOn: [
            (s) => [s.themeMode, s.darkModeSystemPreference, sceneLogic.selectors.sceneConfig, s.theme],
            (themeMode, darkModeSystemPreference, sceneConfig, theme) => {
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
                // NOTE: Unauthenticated users always get the light mode until we have full support for dark mode there
                if (sceneConfig?.allowUnauthenticated || sceneConfig?.onlyUnauthenticated) {
                    return false
                }

                return themeMode === 'system' ? darkModeSystemPreference : themeMode === 'dark'
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        saveCustomCss() {
            actions.setPersistedCustomCss(values.previewingCustomCss)
            actions.setPreviewingCustomCss(null)
        },
    })),
    events(({ cache, actions }) => ({
        afterMount() {
            cache.disposables.add(() => {
                const prefersColorSchemeMedia = window.matchMedia('(prefers-color-scheme: dark)')
                const onPrefersColorSchemeChange = (e: MediaQueryListEvent): void =>
                    actions.syncDarkModePreference(e.matches)
                prefersColorSchemeMedia.addEventListener('change', onPrefersColorSchemeChange)
                return () => prefersColorSchemeMedia.removeEventListener('change', onPrefersColorSchemeChange)
            }, 'prefersColorSchemeListener')
        },
    })),
])
