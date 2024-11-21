import { actions, afterMount, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'
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
    reducers({}),
    actions({
        addColor: true,
    }),
    forms(() => ({
        theme: {
            defaults: {},
            submit: async () => {},
        },
    })),
    afterMount(({ actions }) => {
        actions.loadThemes()
    }),
])
