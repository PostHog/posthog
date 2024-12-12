import { actions, connect, kea, listeners, path } from 'kea'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { dataColorThemesModalLogic } from './dataColorThemeModalLogic'
import type { dataColorThemesLogicType } from './dataColorThemesLogicType'

export const dataColorThemesLogic = kea<dataColorThemesLogicType>([
    path(['scenes', 'settings', 'environment', 'dataColorThemesLogic']),
    connect({
        values: [dataThemeLogic, ['themes', 'themesLoading', 'defaultTheme', 'posthogTheme']],
        actions: [dataColorThemesModalLogic, ['openModal']],
    }),
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
    })),
])
