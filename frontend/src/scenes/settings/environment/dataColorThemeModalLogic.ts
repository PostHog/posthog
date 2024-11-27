import { lemonToast } from '@posthog/lemon-ui'
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
        duplicateColor: (index: number) => ({ index }),
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
                duplicateColor: (theme, { index }) => ({
                    ...theme,
                    colors: theme.colors.flatMap((color, idx) => (idx === index ? [color, color] : [color])),
                }),
                removeColor: (theme, { index }) => ({
                    ...theme,
                    colors: theme.colors.filter((_, idx) => idx !== index),
                }),
            },
        ],
    }),
    forms(({ actions }) => ({
        theme: {
            submit: async ({ id, name, colors }, breakpoint) => {
                const payload: DataColorThemeModel = {
                    name,
                    colors,
                }

                breakpoint()

                try {
                    const updatedTheme = id
                        ? await api.dataColorThemes.update(id, payload)
                        : await api.dataColorThemes.create(payload)

                    actions.closeModal()

                    return updatedTheme
                } catch (error: any) {
                    if (error.data?.attr && error.data?.detail) {
                        const field = error.data?.attr?.replace(/_/g, ' ')
                        lemonToast.error(`Error saving data color theme: ${field}: ${error.data.detail}`)
                    } else {
                        lemonToast.error(`Error saving data color theme`)
                    }
                }
            },
            errors: (theme) => ({
                name: !theme?.name ? 'This field is required' : undefined,
            }),
        },
    })),
])
