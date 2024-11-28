import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DataColorThemeModel } from '~/types'

import type { dataThemeLogicType } from './dataThemeLogicType'
import { teamLogic } from './teamLogic'

export const dataThemeLogic = kea<dataThemeLogicType>([
    path(['scenes', 'dataThemeLogic']),
    connect({ values: [teamLogic, ['currentTeam']] }),
    loaders({
        themes: [
            null as null | DataColorThemeModel[],
            {
                loadThemes: async () => await api.dataColorThemes.list(),
            },
        ],
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
                (themeId: string | number | null | undefined): DataColorTheme | null => {
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

                    return null
                },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadThemes()
    }),
])
