import { afterMount, connect, kea, listeners, path } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import { CoreMemory } from '~/types'

import type { maxSettingsLogicType } from './maxSettingsLogicType'

interface CoreMemoryForm {
    text: string
}

export const maxSettingsLogic = kea<maxSettingsLogicType>([
    path(['scenes', 'project', 'Settings', 'maxSettingsLogic']),

    connect({ values: [organizationLogic, ['currentOrganization']] }),

    loaders(() => ({
        coreMemory: {
            __default: [] as CoreMemory[],
            loadCoreMemory: async () => {
                return await api.coreMemory.list()
            },
            createCoreMemory: async ({ text }: Pick<CoreMemory, 'text'>) => {
                const response = await api.coreMemory.create({
                    text,
                })
                lemonToast.success('Max memory created')
                return [response]
            },
            updateCoreMemory: async (id: CoreMemory['id'], data: Pick<CoreMemory, 'text'>) => {
                const response = await api.coreMemory.update(id, data)
                lemonToast.success('Max memory updated')
                return [response]
            },
        },
    })),

    forms(({ actions }) => ({
        coreMemoryForm: {
            defaults: { text: '' } as CoreMemoryForm,
            submit: ({ text }) => {
                actions.createCoreMemory({ text })
            },
        },
    })),

    listeners(({ actions }) => ({
        loadCoreMemory: (payload: PaginatedResponse<CoreMemory>) => {
            {
                if (payload.results.length > 0) {
                    actions.setCoreMemoryFormValue('text', payload.results[0].text)
                }
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadCoreMemory()
    }),
])
