import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DataColorTheme } from 'lib/colors'

import { DataColorThemeModel } from '~/types'

import type { dataThemeLogicType } from './dataThemeLogicType'
import { teamLogic } from './teamLogic'

/** Returns a data color theme from the backend side theme model. */
export function convertApiTheme(apiTheme: DataColorThemeModel): DataColorTheme {
    return apiTheme.colors.reduce((theme, color, index) => {
        theme[`preset-${index + 1}`] = color
        return theme
    }, {})
}

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
                return environmentTheme || themes.find((theme) => theme.is_global)
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
                        return convertApiTheme(customTheme)
                    }

                    if (defaultTheme) {
                        return convertApiTheme(defaultTheme)
                    }

                    return null
                },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadThemes()
    }),
])
