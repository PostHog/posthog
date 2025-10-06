import { actions, afterMount, connect, kea, path, props, reducers, selectors, useValues } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { DataColorTheme, DataColorToken } from 'lib/colors'

import { DataColorThemeModel } from '~/types'

import type { dataThemeLogicType } from './dataThemeLogicType'
import { teamLogic } from './teamLogic'

export function getColorFromToken(theme: DataColorTheme, colorToken: string): string {
    const colorNo = parseInt(colorToken.replace('preset-', ''))
    const availableColors = Object.keys(theme).length

    // once all colors are exhausted, start again from the beginning
    const wrappedNum = ((colorNo - 1) % availableColors) + 1
    return theme[`preset-${wrappedNum}`]
}

export const ThemeName = ({ id }: { id: number }): JSX.Element => {
    const { themes } = useValues(dataThemeLogic)
    const theme = themes?.find((theme) => theme.id === id)

    return theme ? <span>{theme.name}</span> : <span className="italic">No theme found for id: {id}</span>
}

export type DataThemeLogicProps = {
    themes?: DataColorThemeModel[]
}

export const dataThemeLogic = kea<dataThemeLogicType>([
    props({} as DataThemeLogicProps),
    path(['scenes', 'dataThemeLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeam']] })),
    actions({ setThemes: (themes) => ({ themes }) }),
    loaders(({ props }) => ({
        themes: [
            props.themes || null,
            {
                loadThemes: async () => await api.dataColorThemes.list(),
            },
        ],
    })),
    reducers({
        themes: {
            setThemes: (_, { themes }) => themes,
        },
    }),
    selectors({
        posthogTheme: [
            (s) => [s.themes],
            (themes) => {
                if (!themes) {
                    return null
                }

                return themes.sort((theme) => theme.id).find((theme) => theme.is_global)
            },
        ],
        defaultTheme: [
            (s) => [s.currentTeam, s.themes, s.posthogTheme],
            (currentTeam, themes, posthogTheme): DataColorThemeModel | null => {
                if (!currentTeam || !themes) {
                    return null
                }

                // use the posthog theme unless someone set a specfic theme for the team
                const environmentTheme = themes.find((theme) => theme.id === currentTeam.default_data_theme)
                return environmentTheme || posthogTheme || null
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
                        }, {} as DataColorTheme)
                    }

                    if (defaultTheme) {
                        return defaultTheme.colors.reduce((theme, color, index) => {
                            theme[`preset-${index + 1}`] = color
                            return theme
                        }, {} as DataColorTheme)
                    }

                    return null
                },
        ],
        getColorFromToken: [
            (s) => [s.getTheme],
            (getTheme: (themeId: string | number | null | undefined) => DataColorTheme | null) =>
                (themeId: string | number | null | undefined, colorToken: string): string | null => {
                    const theme = getTheme(themeId)
                    if (!theme) {
                        return null
                    }
                    return getColorFromToken(theme, colorToken)
                },
        ],
        getAvailableColorTokens: [
            (s) => [s.getTheme],
            (getTheme: (themeId: string | number | null | undefined) => DataColorTheme | null) =>
                (themeId: string | number | null | undefined): DataColorToken[] | null => {
                    const theme = getTheme(themeId)
                    if (!theme) {
                        return null
                    }
                    return Object.keys(theme || {}) as DataColorToken[]
                },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadThemes()
    }),
])
