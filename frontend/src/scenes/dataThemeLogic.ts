import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { getColorVar, _DataColorTheme } from 'lib/colors'

import type { dataThemeLogicType } from './dataThemeLogicType'

const POSTHOG_THEME: _DataColorTheme = {
    'preset-1': getColorVar('data-color-1'),
    'preset-2': getColorVar('data-color-2'),
    'preset-3': getColorVar('data-color-3'),
    'preset-4': getColorVar('data-color-4'),
    'preset-5': getColorVar('data-color-5'),
    'preset-6': getColorVar('data-color-6'),
    'preset-7': getColorVar('data-color-7'),
    'preset-8': getColorVar('data-color-8'),
    'preset-9': getColorVar('data-color-9'),
    'preset-10': getColorVar('data-color-10'),
    'preset-11': getColorVar('data-color-11'),
    'preset-12': getColorVar('data-color-12'),
    'preset-13': getColorVar('data-color-13'),
    'preset-14': getColorVar('data-color-14'),
    'preset-15': getColorVar('data-color-15'),
}
import { teamLogic } from './teamLogic'

export const dataThemeLogic = kea<dataThemeLogicType>([
    path(['scenes', 'dataThemeLogic']),
    connect({ values: [teamLogic, ['currentTeam']] }),
    loaders({
        themes: {
            loadThemes: async () => await api.dataColorThemes.list(),
        },
    }),
    selectors({
        defaultTheme: [
            (s) => [s.currentTeam, s.themes],
            (currentTeam, themes) => {
                if (!currentTeam || !themes) {
                    return null
                }

                const environmentTheme = themes.find((theme) => theme.id === currentTeam.default_data_theme)
                // TODO: better way to detect the posthog default theme
                return environmentTheme || themes.find((theme) => theme.id === 1)
            },
        ],
        getTheme: [
            (s) => [s.themes, s.defaultTheme],
            (themes, defaultTheme) =>
                (themeId: string | number): _DataColorTheme => {
                    let customTheme

                    if (Number.isInteger(themeId) && themes != null) {
                        customTheme = themes.find((theme) => theme.id === themeId)
                    }

                    if (customTheme) {
                        return customTheme.colors.reduce((theme, color, index) => {
                            theme[`preset-${index + 1}`] = color
                            return theme
                        }, {})
                    }

                    if (defaultTheme) {
                        return defaultTheme.colors.reduce((theme, color, index) => {
                            theme[`preset-${index + 1}`] = color
                            return theme
                        }, {})
                    }

                    return POSTHOG_THEME
                },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadThemes()
    }),
])
