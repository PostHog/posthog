import { actions, connect, kea, listeners, path } from 'kea'

import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { dataColorThemesModalLogic } from './dataColorThemeModalLogic'
import type { dataColorThemesLogicType } from './dataColorThemesLogicType'

export const dataColorThemesLogic = kea<dataColorThemesLogicType>([
    path(['scenes', 'settings', 'environment', 'dataColorThemesLogic']),
    connect(() => ({
        values: [dataThemeLogic, ['themes', 'themesLoading', 'defaultTheme', 'posthogTheme']],
        actions: [dataColorThemesModalLogic, ['openModal', 'submitThemeSuccess'], dataThemeLogic, ['setThemes']],
    })),
    actions({
        selectTheme: (id: 'new' | number | null) => ({ id }),
    }),
    listeners(({ values, actions }) => ({
        selectTheme: ({ id }) => {
            // we're not yet initialized
            if (values.themes == null || values.posthogTheme == null || id == null) {
                return
            }

            if (id === 'new') {
                const { id, name, is_global, ...newTheme } = values.posthogTheme
                actions.openModal(newTheme)
            } else {
                const existingTheme = values.themes.find((theme) => theme.id === id)
                actions.openModal(existingTheme)
            }
        },
        submitThemeSuccess: ({ theme }) => {
            const existingTheme = values.themes!.find((t) => t.id === theme.id)
            if (existingTheme != null) {
                const updatedThemes = values.themes!.map((t) => (t.id === theme.id ? theme : t))
                actions.setThemes(updatedThemes)
            } else {
                actions.setThemes([...values.themes!, theme])
            }
        },
    })),
])
