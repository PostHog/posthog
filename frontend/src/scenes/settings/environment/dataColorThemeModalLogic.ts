import { actions, kea, path, reducers } from 'kea'
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
            submit: async ({ id, name, colors }, breakpoint) => {
                console.debug('name', name)
                console.debug('colors', colors)

                const payload: DataColorThemeModel = {
                    name,
                    colors,
                }

                const updatedTheme = id
                    ? await api.dataColorThemes.update(id, payload)
                    : await api.dataColorThemes.create(payload)

                breakpoint()
            },
        },
    })),
])
