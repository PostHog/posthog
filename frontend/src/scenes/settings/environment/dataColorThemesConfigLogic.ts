import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { dataColorThemesConfigLogicType } from './dataColorThemesConfigLogicType'

export const dataColorThemesConfigLogic = kea<dataColorThemesConfigLogicType>([
    path(['scenes', 'settings', 'environment', 'dataColorThemesConfigLogic']),
    loaders({
        themes: {
            loadThemes: async () => await api.dataColorThemes.list(),
        },
    }),
    reducers({
        selectedThemeId: [
            null as number | null,
            {
                selectTheme: (_, { id }) => id,
            },
        ],
    }),
    selectors({
        selectedTheme: [
            (s) => [s.themes, s.selectedThemeId],
            (themes, selectedThemeId) => {
                if (themes == null || selectedThemeId == null) {
                    return null
                }

                return themes.find((theme) => theme.id === selectedThemeId)
            },
        ],
    }),
    actions({
        selectTheme: (id: number | null) => ({ id }),
    }),
    // forms(() => ({
    //     theme: {
    //         defaults: {},
    //         submit: async () => {},
    //     },
    // })),
    afterMount(({ actions }) => {
        actions.loadThemes()
    }),
])
