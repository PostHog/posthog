import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { CoreMemory } from '~/types'

import type { maxSettingsLogicType } from './maxSettingsLogicType'

export type CoreMemoryForm = {
    text: string
}

export const maxSettingsLogic = kea<maxSettingsLogicType>([
    path(['scenes', 'project', 'Settings', 'maxSettingsLogic']),

    actions({
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
    }),

    reducers({
        isLoading: [
            false,
            {
                loadCoreMemory: () => true,
                loadCoreMemorySuccess: () => false,
                loadCoreMemoryFailure: () => false,
            },
        ],

        isUpdating: [
            false,
            {
                createCoreMemory: () => true,
                createCoreMemorySuccess: () => false,
                createCoreMemoryFailure: () => false,
                updateCoreMemory: () => true,
                updateCoreMemorySuccess: () => false,
                updateCoreMemoryFailure: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        coreMemory: {
            __default: null as CoreMemory | null,
            loadCoreMemory: async (): Promise<CoreMemory | null> => {
                try {
                    const response = await api.coreMemory.list()
                    return response.results[0] || null
                } catch (error) {
                    // Non-OK responses (e.g. 403 when lacking access to the environment, or upstream
                    // timeouts) shouldn't surface as uncaught frontend errors — fall back to empty state.
                    // Anything that isn't an HTTP error (a real regression in the API client) still propagates.
                    if (error instanceof ApiError) {
                        return null
                    }
                    throw error
                }
            },
            updateCoreMemory: async (data: CoreMemoryForm) => {
                if (!values.coreMemory) {
                    const response = await api.coreMemory.create(data)
                    lemonToast.success('PostHog AI memory has been created.')
                    return response
                }

                const response = await api.coreMemory.update(values.coreMemory.id, data)
                lemonToast.success('PostHog AI memory has been updated.')
                return response
            },
        },
    })),

    forms(({ actions }) => ({
        coreMemoryForm: {
            defaults: { text: '' } as CoreMemoryForm,
            submit: ({ text }) => {
                actions.updateCoreMemory({ text })
            },
        },
    })),

    listeners(({ actions }) => ({
        loadCoreMemorySuccess: ({ coreMemory }) => {
            if (coreMemory) {
                actions.setCoreMemoryFormValue('text', coreMemory.text)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadCoreMemory()
    }),
])
