import { actions, afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { dataColorThemesModalLogic } from './dataColorThemeModalLogic'
import type { dataColorThemesLogicType } from './dataColorThemesLogicType'

export const dataColorThemesLogic = kea<dataColorThemesLogicType>([
    path(['scenes', 'settings', 'environment', 'dataColorThemesLogic']),
    connect({
        actions: [dataColorThemesModalLogic, ['openModal']],
    }),
    loaders({
        themes: {
            loadThemes: async () => await api.dataColorThemes.list(),
        },
    }),
    actions({
        selectTheme: (id: 'new' | number | null) => ({ id }),
    }),
    listeners(({ values, actions }) => ({
        selectTheme: ({ id }) => {
            // we're not yet initialized
            if (values.themes == null || id == null) {
                return
            }

            if (id === 'new') {
                // TODO: better way to detect the posthog default theme - likely is_global and trait
                const defaultTheme = values.themes.find((theme) => theme.name.includes('Default'))
                const { id, ...newTheme } = defaultTheme
                actions.openModal(newTheme)
            }

            const existingTheme = values.themes.find((theme) => theme.id === id)
            actions.openModal(existingTheme)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadThemes()
    }),
])
