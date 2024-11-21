import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { DataColorThemeModel } from 'lib/colors'

import type { dataColorThemesModalLogicType } from './dataColorThemeModalLogicType'

export const dataColorThemesModalLogic = kea<dataColorThemesModalLogicType>([
    path(['scenes', 'settings', 'environment', 'dataColorThemesModalLogic']),
    actions({
        openModal: (theme) => ({ theme }),
    }),
    reducers({
        theme: [
            null as null | DataColorThemeModel,
            {
                openModal: (_, { theme }) => theme,
            },
        ],
    }),
    forms(({ values }) => ({
        theme: {
            // defaults: {},
            submit: async () => {},
        },
    })),
    afterMount(({ actions }) => {
        // actions.loadThemes()
    }),
])
