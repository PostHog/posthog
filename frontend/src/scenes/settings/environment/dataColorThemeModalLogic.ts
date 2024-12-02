import { lemonToast } from '@posthog/lemon-ui'
import { actions, kea, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'

import { DataColorThemeModel } from '~/types'

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
        theme: {
            openModal: (_, { theme }) => theme,
            closeModal: () => null,
            addColor: (theme) => {
                if (theme == null) {
                    return null
                }
                return {
                    ...theme,
                    colors: [...theme.colors, theme.colors[theme.colors.length - 1] || '#1d4aff'],
                }
            },
            duplicateColor: (theme, { index }) => {
                if (theme == null) {
                    return null
                }
                return {
                    ...theme,
                    colors: theme.colors.flatMap((color, idx) => (idx === index ? [color, color] : [color])),
                }
            },
            removeColor: (theme, { index }) => {
                if (theme == null) {
                    return null
                }
                return {
                    ...theme,
                    colors: theme.colors.filter((_, idx) => idx !== index),
                }
            },
        },
    }),
    forms(({ actions }) => ({
        theme: {
            defaults: null as DataColorThemeModel | null,
            submit: async (formValues, breakpoint) => {
                const { id, name, colors } = formValues || {}
                const payload: Partial<DataColorThemeModel> = {
                    name,
                    colors,
                }

                breakpoint()

                try {
                    id ? await api.dataColorThemes.update(id, payload) : await api.dataColorThemes.create(payload)
                    actions.closeModal()
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
