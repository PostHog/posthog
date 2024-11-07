import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import type { themeLogicType } from './themeLogicType'
import { Theme, themes } from './themes'

type CustomThemeType = Record<
    'tron' | 'retro' | 'fisher-price' | 'usa',
    {
        title: string
        baseTheme: 'light' | 'dark'
        styles: string
        primaryColors: string[]
        disabled: boolean
    }
>

export const THEMES: CustomThemeType = {
    tron: {
        title: 'TRON',
        baseTheme: 'dark',
        styles: '',
        primaryColors: ['black', '#00FF01', 'black'],
        disabled: false,
    },
    retro: {
        title: 'Windows 95',
        baseTheme: 'light',
        styles: '',
        primaryColors: ['#008282', '#C3C3C3', '#02007F'],
        disabled: true,
    },
    'fisher-price': {
        title: 'Fisher Price',
        baseTheme: 'light',
        styles: '',
        primaryColors: ['red', 'green', 'blue'],
        disabled: true,
    },
    usa: {
        title: 'USA',
        baseTheme: 'light',
        styles: '',
        primaryColors: ['#0A3161', '#FFFFFF', '#B31942'],
        disabled: true,
    },
}

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    connect({
        values: [userLogic, ['themeMode'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        syncDarkModePreference: (darkModePreference: boolean) => ({ darkModePreference }),
        setTheme: (theme: string | null) => ({ theme }),
        setCustomThemeId: (themeId: string | null) => ({ themeId }),
        setCustomTheme: (id: string, theme: CustomThemeType) => ({ id, theme }),
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
        customThemeId: [
            null as string | null,
            { persist: true },
            {
                setCustomThemeId: (_, { themeId }) => themeId,
            },
        ],
        customThemes: [
            THEMES,
            { persist: true },
            {
                setCustomTheme: (state, { id, theme }) => ({ ...state, [id]: theme }),
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
        },
        beforeUnmount() {
            cache.prefersColorSchemeMedia.removeEventListener('change', cache.onPrefersColorSchemeChange)
        },
    })),
])
