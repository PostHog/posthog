import { actions, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { DataColorThemeModelPayload } from '~/types'

import type { dataColorThemesModalLogicType } from './dataColorThemeModalLogicType'

const PAYLOAD_DEFAULT: DataColorThemeModelPayload = { name: '', colors: [] }

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
        isOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        theme: [
            { name: '', colors: [] } as DataColorThemeModelPayload,
            {
                addColor: (theme) => ({
                    ...theme,
                    colors: [...(theme.colors || []), theme.colors[theme.colors.length - 1] || '#1d4aff'],
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
            defaults: PAYLOAD_DEFAULT,
            submit: async ({ id, name, colors }, breakpoint): Promise<DataColorThemeModelPayload> => {
                const payload: DataColorThemeModelPayload = {
                    name: name || '',
                    colors: colors || [],
                }

                breakpoint()

                try {
                    const updatedTheme = id
                        ? await api.dataColorThemes.update(id, payload)
                        : await api.dataColorThemes.create(payload)

                    lemonToast.success(updatedTheme ? 'Theme saved.' : 'Theme created.')
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

                return payload
            },
            errors: (theme) => ({
                name: !theme?.name ? 'This field is required' : undefined,
            }),
        },
    })),
    listeners(({ actions }) => ({
        openModal: ({ theme }) => {
            actions.resetTheme(theme)
        },
    })),
])
