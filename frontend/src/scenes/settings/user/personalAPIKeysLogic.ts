import { kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { PersonalAPIKeyType } from '~/types'

import type { personalAPIKeysLogicType } from './personalAPIKeysLogicType'

export const personalAPIKeysLogic = kea<personalAPIKeysLogicType>([
    path(['lib', 'components', 'PersonalAPIKeys', 'personalAPIKeysLogic']),
    loaders(({ values }) => ({
        keys: [
            [] as PersonalAPIKeyType[],
            {
                loadKeys: async () => {
                    const response: PersonalAPIKeyType[] = await api.get('api/personal_api_keys/')
                    return response
                },
                createKey: async (label: string) => {
                    const newKey: PersonalAPIKeyType = await api.create('api/personal_api_keys/', {
                        label,
                    })
                    return [newKey, ...values.keys]
                },
                deleteKey: async (key: PersonalAPIKeyType) => {
                    await api.delete(`api/personal_api_keys/${key.id}/`)
                    return values.keys.filter((filteredKey) => filteredKey.id != key.id)
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
