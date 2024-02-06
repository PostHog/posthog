import { actions, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { PersonalAPIKeyType } from '~/types'

import type { personalAPIKeysLogicType } from './personalAPIKeysLogicType'

export const personalAPIKeysLogic = kea<personalAPIKeysLogicType>([
    path(['lib', 'components', 'PersonalAPIKeys', 'personalAPIKeysLogic']),
    actions({
        loadKeys: true,
        createKey: (label: string) => ({ label }),
        updateKey: (data: Partial<Pick<PersonalAPIKeyType, 'label' | 'scopes'>>) => data,
        deleteKey: (id: PersonalAPIKeyType['id']) => ({ id }),
    }),
    loaders(({ values }) => ({
        keys: [
            [] as PersonalAPIKeyType[],
            {
                loadKeys: async () => {
                    return await api.personalApiKeys.list()
                },
                createKey: async ({ label }) => {
                    const newKey = await api.personalApiKeys.create({ label })
                    return [newKey, ...values.keys]
                },

                updateKey: async (payload) => {
                    const updatedKey = await api.personalApiKeys.update(values.keys[0].id, payload)

                    return values.keys.map((key) => {
                        if (key.id === updatedKey.id) {
                            return updatedKey
                        }
                        return key
                    })
                },
                deleteKey: async ({ id }) => {
                    await api.personalApiKeys.delete(id)
                    await api.delete(`api/personal_api_keys/${id}/`)
                    return values.keys.filter((filteredKey) => filteredKey.id != id)
                },
            },
        ],
    })),
    listeners(() => ({
        createKeySuccess: async ({ keys }: { keys: PersonalAPIKeyType[] }) => {
            keys[0]?.value && (await copyToClipboard(keys[0].value, 'personal API key value'))
        },
        deleteKeySuccess: () => {
            lemonToast.success(`Personal API key deleted`)
        },
    })),
])
