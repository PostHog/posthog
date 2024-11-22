import { actions, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { DataColorThemeModel } from 'lib/colors'

import type { dataColorThemesModalLogicType } from './dataColorThemeModalLogicType'

export const dataColorThemesModalLogic = kea<dataColorThemesModalLogicType>([
    path(['scenes', 'settings', 'environment', 'dataColorThemesModalLogic']),
    actions({
        openModal: (theme) => ({ theme }),
        closeModal: true,
        addColor: true,
        removeColor: (index: number) => ({ index }),
    }),
    reducers({
        theme: [
            null as null | DataColorThemeModel,
            {
                openModal: (_, { theme }) => theme,
                closeModal: () => null,
                addColor: (theme) => ({
                    ...theme,
                    colors: [...theme.colors, theme.colors[theme.colors.length - 1] || '#1d4aff'],
                }),
                removeColor: (theme, { index }) => ({
                    ...theme,
                    colors: theme.colors.filter((_, idx) => idx !== index),
                }),
            },
        ],
    }),
    forms(({ values }) => ({
        theme: {
            // defaults: {},
            submit: async ({ id, name, colors }, breakpoint) => {
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
